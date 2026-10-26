import io, re, os
from datetime import datetime
import pandas as pd
import streamlit as st
import fitz
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

st.set_page_config(page_title="Maintenance Invoice Automation", layout="wide")
st.title("Maintenance Invoice Automation Dashboard")
st.caption("Bulk invoice extraction with text-PDF parsing, optional OCR for scanned files, review controls and Excel export. Always verify extracted values before posting.")

with st.sidebar:
    st.subheader("Extraction settings")
    ocr_enabled = st.checkbox("Use OCR when PDF text is missing / scan is detected", value=True)
    tesseract_path = st.text_input("Tesseract executable path (if installed)", value=r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    st.caption("Scanned PDFs/images require Tesseract OCR installed on this computer. Text-based PDFs do not.")

uploads = st.file_uploader("Upload multiple invoice files", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"], accept_multiple_files=True)

MONEY = r"(?:₹\s*)?\(?-?\d[\d,]*(?:\.\d{1,2})?\)?"

def money_values(s):
    vals=[]
    for x in re.findall(MONEY, s):
        x=x.replace('₹','').replace(',','').replace(' ','')
        neg=x.startswith('(') and x.endswith(')')
        x=x.strip('()')
        try:
            v=float(x)
            vals.append(-v if neg else v)
        except ValueError:
            pass
    return vals

def clean_text(s):
    s=s.replace('\xa0',' ').replace('\r','\n')
    s=re.sub(r'[ \t]+',' ',s)
    s=re.sub(r'\n{3,}','\n\n',s)
    return s.strip()

def configure_tesseract():
    try:
        import pytesseract
        if tesseract_path.strip() and os.path.isfile(tesseract_path.strip()):
            pytesseract.pytesseract.tesseract_cmd=tesseract_path.strip()
        return pytesseract
    except Exception:
        return None

def ocr_image(im):
    pytesseract=configure_tesseract()
    if pytesseract is None:
        return "", "pytesseract package unavailable"
    try:
        im=ImageOps.grayscale(im)
        im=ImageOps.autocontrast(im)
        im=ImageEnhance.Contrast(im).enhance(1.5)
        im=im.filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(im, config="--oem 3 --psm 6"), "OCR used"
    except Exception as e:
        return "", f"OCR failed: {e}"

def read_upload(f):
    data=f.getvalue(); name=f.name.lower(); parts=[]; method=[]
    if name.endswith('.pdf'):
        try:
            doc=fitz.open(stream=data, filetype='pdf')
            for page in doc:
                page_text=page.get_text("text") or ""
                # Text-based pages are reliable; OCR only if almost no readable text exists.
                if ocr_enabled and len(re.sub(r'\W','',page_text)) < 35:
                    pix=page.get_pixmap(matrix=fitz.Matrix(2.5,2.5), alpha=False)
                    im=Image.open(io.BytesIO(pix.tobytes('png')))
                    otext, status=ocr_image(im)
                    if len(otext.strip()) > len(page_text.strip()):
                        page_text=otext
                    method.append(status)
                else:
                    method.append("PDF text extracted")
                parts.append(page_text)
        except Exception as e:
            return "", f"PDF read failed: {e}"
    else:
        try:
            im=Image.open(io.BytesIO(data))
            text,status=ocr_image(im)
            parts.append(text); method.append(status)
        except Exception as e:
            return "", f"Image read failed: {e}"
    return clean_text('\n'.join(parts)), '; '.join(dict.fromkeys(method))

def first_match(patterns, text, flags=re.I|re.M):
    for pat in patterns:
        m=re.search(pat,text,flags)
        if m:
            val=m.group(1).strip(' :#\t\n')
            if val:
                return val
    return ""

def to_float(s):
    if s is None: return None
    s=str(s).strip().replace('₹','').replace(',','').replace(' ','')
    if not s: return None
    neg=s.startswith('(') and s.endswith(')')
    s=s.strip('()')
    try:
        n=float(s)
        return -n if neg else n
    except ValueError: return None

def values_after_label(text, label_patterns, lookahead=5):
    """Return numeric values close to a labelled summary, including labels whose values wrap to later lines."""
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if any(re.search(p,line,re.I) for p in label_patterns):
            chunk=' '.join(lines[i:min(len(lines),i+lookahead+1)])
            # Stop before a new summary label so unrelated numbers aren't absorbed.
            chunk=re.split(r'(?i)\b(?:Net Bill Amount|Sub Total Amount|Less Discount|CGST|SGST|IGST|Gate Pass)\b', chunk)
            # First split segment may be empty because the matched label is in it; use raw local chunk instead,
            # but only the first few lines to avoid capturing unrelated lower-page values.
            raw=' '.join(lines[i:min(len(lines),i+lookahead+1)])
            vals=money_values(raw)
            if vals:
                # Ignore percentage values and date fragments are not parsed as money by the decimal pattern.
                return vals
    return []

def labeled_amount(text, labels):
    vals=values_after_label(text,labels,lookahead=4)
    return vals[-1] if vals else None

def labeled_value(text, labels, validator, lookahead=5):
    lines=text.splitlines()
    for i,line in enumerate(lines):
        if any(re.search(p,line,re.I) for p in labels):
            # First check text after the label on the same line, then the next few lines.
            chunk=' '.join(lines[i:min(len(lines),i+lookahead+1)])
            for candidate in re.findall(r'[A-Z0-9][A-Z0-9./_-]{2,}',chunk,re.I):
                if validator(candidate): return candidate.strip()
    return ""


def amounts_on_line(line):
    """Parse monetary values with exactly two decimal places from one summary line."""
    return [float(x.replace(',', '')) for x in re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line)]

def extract_non_fort_summary(text, lines):
    """Vendor-specific summary parsing for Popular and Star Motor Works layouts."""
    result = {
        'supplier': '', 'inv': '', 'inv_date': '', 'vehicle': '',
        'parts_before': None, 'parts_disc': None, 'labour_before': None, 'labour_disc': None,
        'pcg': None, 'lcg': None, 'psg': None, 'lsg': None,
        'cgst_total': None, 'sgst_total': None, 'total': None
    }
    # Common vendor identity/registration fields
    result['supplier'] = first_match([
        r'(?im)^\s*(Star Motor Works)\s*$',
        r'(?im)^\s*(Popular Vehicles and Services Ltd)\s*$',
        r'(?im)^\s*For\s+(POPULAR VEHICLES AND SERVICES LTD|STAR MOTOR WORKS)\b[^\n]*'
    ], text)
    if not result['supplier']:
        result['supplier'] = first_match([r'(?im)^\s*For\s+([^\n]{3,120})'], text)
    result['supplier'] = re.sub(r'\s+', ' ', result['supplier']).strip(' .,:;')
    result['inv'] = first_match([
        r'(?i)\bInvoice\s*No\.?\s*:\s*([A-Z0-9/-]{2,40})',
        r'(?i)\bBill\s*No\.?\s*:\s*([A-Z0-9/-]{1,40})'
    ], text)
    result['inv_date'] = first_match([
        r'(?i)\bBill\s*Date\s*:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})',
        r'(?i)\bDate\s*:\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})'
    ], text)
    # Normalize US-style date only for Popular's MM/DD/YYYY date format.
    if result['inv_date'] and re.match(r'^\d{1,2}/\d{1,2}/\d{4}$', result['inv_date']):
        a,b,y=map(int,result['inv_date'].split('/'))
        if a <= 12 and b <= 12 and a > 0 and b > 0:
            # Popular header uses MM/DD/YYYY; Star uses DD/MM/YYYY.
            if re.search(r'Popular Vehicles', result['supplier'], re.I):
                result['inv_date']=f'{b:02d}/{a:02d}/{y:04d}'
    result['vehicle'] = first_match([
        r'(?i)(?:Reg\.?\s*No\.?|Registration\s*No\.?)\s*:\s*([A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{3,4})'
    ], text).replace(' ','').upper()

    if re.search(r'(?i)Star Motor Works', result['supplier'] + ' ' + text[:500]):
        # Star uses Products and Services sections and a Grand Total row.
        result['parts_before'] = None
        result['labour_before'] = None
        for line in lines:
            if re.search(r'^\s*Total\s*:', line, re.I):
                vals=amounts_on_line(line)
                # The first Total after Products is the products-with-GST total, not taxable base.
                # Detailed table totals are verified from the invoice summary where available.
        # Explicit taxable summary on page 2: Taxable Products Amount / Taxable Service Amount.
        mp=re.search(r'(?i)Taxable\s+Products\s+Amount\s*\(Rs\.?\)\s*:\s*([\d,]+(?:\.\d{1,2})?)', text)
        ms=re.search(r'(?i)Taxable\s+Service\s+Amount\s*\(Rs\.?\)\s*:\s*([\d,]+(?:\.\d{1,2})?)', text)
        if mp: result['parts_before']=float(mp.group(1).replace(',',''))
        if ms: result['labour_before']=float(ms.group(1).replace(',',''))
        # Product and service GST summary; values may be rounded whole rupees, so use detailed grand-total row.
        cgst_total=first_match([r'(?i)Grand\s+Total\s*:.*?([\d,]+\.\d{2})\s+0\s+[\d,]+\.\d{2}\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'], text)
        # More robust line parse: Grand Total row has taxable total, discount, taxable net, CGST, SGST, IGST, grand total.
        for line in lines:
            if re.search(r'Grand\s+Total\s*:', line, re.I):
                vals=amounts_on_line(line)
                # Typical row: taxable gross, discount, taxable net, CGST, SGST, IGST, grand total.
                if len(vals)>=5:
                    result['cgst_total']=vals[-4]
                    result['sgst_total']=vals[-3]
                    result['total']=vals[-1]
        if result['cgst_total'] is None:
            m=re.search(r'(?i)Grand\s+Total\s*:\s*[\d,.]+\s+0\s+[\d,.]+\s+([\d,.]+)\s+([\d,.]+)\s+0\s+0\s+([\d,.]+)',text)
            if m:
                result['cgst_total']=float(m.group(1).replace(',',''))
                result['sgst_total']=float(m.group(2).replace(',',''))
                result['total']=float(m.group(3).replace(',',''))
        # Detail summary lists products/service GST; use exact cents when available.
        prod_cgst=first_match([r'(?i)CGST\s+on\s+Products\s*\(Rs\.?\)\s*:\s*([\d,.]+)'],text)
        serv_cgst=first_match([r'(?i)CGST\s+on\s+Service\s*\(Rs\.?\)\s*:\s*([\d,.]+)'],text)
        prod_sgst=first_match([r'(?i)SGST\s+on\s+Products\s*\(Rs\.?\)\s*:\s*([\d,.]+)'],text)
        serv_sgst=first_match([r'(?i)SGST\s+on\s+Service\s*\(Rs\.?\)\s*:\s*([\d,.]+)'],text)
        if prod_cgst and serv_cgst:
            result['pcg']=float(prod_cgst.replace(',','')); result['lcg']=float(serv_cgst.replace(',',''))
        if prod_sgst and serv_sgst:
            result['psg']=float(prod_sgst.replace(',','')); result['lsg']=float(serv_sgst.replace(',',''))
        # Use detailed exact CGST/SGST totals from the Grand Total row to avoid rounded summary values.
        if result['cgst_total'] is not None and result['pcg'] is not None and result['lcg'] is not None:
            result['cgst_total']=round(result['pcg']+result['lcg'],2)
        if result['sgst_total'] is not None and result['psg'] is not None and result['lsg'] is not None:
            result['sgst_total']=round(result['psg']+result['lsg'],2)
        # Discounts aren't itemized in the summary by category in this vendor layout.
        result['parts_disc']=0.0
        result['labour_disc']=0.0
    elif re.search(r'(?i)Popular Vehicles', result['supplier'] + ' ' + text[:500]):
        # Popular summary has Parts / Labour columns on each row.
        for line in lines:
            if re.search(r'^\s*Sub\s*Total\s*:', line, re.I):
                vals=amounts_on_line(line)
                if len(vals)>=2:
                    result['parts_before'],result['labour_before']=vals[0],vals[-1]
                    break
        for line in lines:
            if re.search(r'^\s*Less\s+Discount\s*:', line, re.I):
                vals=amounts_on_line(line)
                if len(vals)>=2:
                    result['parts_disc'],result['labour_disc']=vals[0],vals[-1]
                    break
        cg=[]; sg=[]
        for line in lines:
            if re.search(r'^\s*CGST\s*@',line,re.I):
                v=amounts_on_line(line)
                if len(v)>=2: cg.append(v)
            if re.search(r'^\s*SGST\s*@',line,re.I):
                v=amounts_on_line(line)
                if len(v)>=2: sg.append(v)
        if cg:
            result['pcg'],result['lcg']=cg[0][0],cg[0][-1]
            result['cgst_total']=round(result['pcg']+result['lcg'],2)
        if sg:
            result['psg'],result['lsg']=sg[0][0],sg[0][-1]
            result['sgst_total']=round(result['psg']+result['lsg'],2)
        for line in lines:
            if re.search(r'Net\s+Bill\s+Amount',line,re.I):
                vals=amounts_on_line(line)
                if vals: result['total']=vals[-1]; break
        result['parts_disc']=result['parts_disc'] if result['parts_disc'] is not None else 0.0
        result['labour_disc']=result['labour_disc'] if result['labour_disc'] is not None else 0.0
    return result

def extract_invoice(f):
    text, method = read_upload(f)
    lines = text.splitlines()

    # Supplier: on this dealer invoice the supplier is printed in the signature block as
    # "For FORT POINT AUTOMOTIVE (CARS) PVT."; do not confuse customer name with supplier.
    supplier = first_match([
        r'(?im)^\s*For\s+([^\n]{3,120})',
        r'(?im)^\s*(?:Supplier|Vendor|Dealer)\s*(?:Name)?\s*[:\-]\s*([^\n]{3,120})'
    ], text)
    if supplier:
        supplier = re.sub(r'\s+', ' ', supplier).strip(' .,:;')

    # Invoice labels and values can be split across lines by PDF text extraction.
    # Do not capture the word "Date" as the invoice number.
    inv = ""
    m = re.search(r'(?is)\bInvoice\s*No\.?\s*[:#]?\s*(.{0,180})', text)
    if m:
        label_chunk = m.group(1)
        # Prefer common workshop bill formats, e.g. 7/BC/26006162 or BC/26006162.
        mm = re.search(r'\b(?:\d{1,3}/)?BC/\d{5,}\b', label_chunk, re.I)
        if mm:
            inv = mm.group(0)
    if not inv:
        # Fallback: inspect values on following lines, excluding labels and dates.
        lines_after = text.splitlines()
        for i, line in enumerate(lines_after):
            if re.search(r'\bInvoice\s*No\b', line, re.I):
                chunk = ' '.join(lines_after[i:i+5])
                candidates = re.findall(r'\b[A-Z0-9]+(?:[/-][A-Z0-9]+){1,}\b', chunk, re.I)
                candidates = [c for c in candidates if not re.fullmatch(r'(?:Date|No|Job/Card)', c, re.I)]
                if candidates:
                    inv = candidates[0]
                    break
    if not inv:
        inv = first_match([
            r'(?i)\bBill\s*No\.?\s*[:#]?\s*((?:\d{1,3}/)?BC/\d{5,})'
        ], text)

    # On this invoice, extraction places "Date :" before the value block,
    # but the actual invoice date is the timestamp immediately after the invoice number.
    inv_date = ""
    if inv:
        inv_pos = text.lower().find(inv.lower())
        nearby = text[inv_pos:inv_pos+120] if inv_pos >= 0 else ""
        dm = re.search(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{4})(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?', nearby)
        if dm:
            inv_date = dm.group(1)
    if not inv_date:
        # Fallback: prefer the explicit invoice date/timestamp, not Job Card Date.
        dm = re.search(r'(?is)Invoice\s*No\.?.{0,180}?\bDate\s*:?\s*(\d{1,2}[/-]\d{1,2}[/-]\d{4})', text)
        if dm:
            inv_date = dm.group(1)
    vehicle = first_match([
        r'(?i)Reg\.?\s*No\.?\s*:\s*([A-Z]{2}\s*\d{1,2}\s*[A-Z]{1,3}\s*\d{3,4})',
        r'\b([A-Z]{2}\d{1,2}[A-Z]{1,3}\d{3,4})\b'
    ], text).replace(' ', '').upper()

    def summary_values(label_pattern):
        """Read only currency-style amounts (with decimal cents) on a matching summary row."""
        for line in lines:
            if re.search(label_pattern, line, re.I):
                # Ignore rates such as @ 9%; retain amounts like 1,383.03 and 0.00.
                after = line.split(':', 1)[-1]
                raw = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', after)
                if raw:
                    return [float(x.replace(',', '')) for x in raw]
        return []

    subtotal = summary_values(r'^\s*Sub\s*Total\s*Amount\b')
    # There can be two Sub Total Amount rows. The first is before discount; the second is net.
    subtotal_rows = []
    for line in lines:
        if re.search(r'^\s*Sub\s*Total\s*Amount\b', line, re.I):
            vals = summary_values_exact = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line.split(':', 1)[-1])
            if vals:
                subtotal_rows.append([float(x.replace(',', '')) for x in vals])
    discount_rows = []
    for line in lines:
        if re.search(r'Less\s+Discount\s+on\s+Parts\s*&\s*Labour', line, re.I):
            vals = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line.split(':', 1)[-1])
            if vals:
                discount_rows.append([float(x.replace(',', '')) for x in vals])
    parts_before = labour_before = parts_disc = labour_disc = None
    if subtotal_rows:
        # This invoice's summary columns are Parts / Other (usually 0) / Labour.
        first = subtotal_rows[0]
        if len(first) >= 3:
            parts_before, labour_before = first[0], first[-1]
        elif len(first) == 2:
            parts_before, labour_before = first
    if discount_rows:
        first = discount_rows[0]
        if len(first) >= 3:
            parts_disc, labour_disc = first[0], first[-1]
        elif len(first) == 2:
            parts_disc, labour_disc = first

    cgst_rows, sgst_rows = [], []
    for line in lines:
        if re.search(r'^\s*CGST\s*@', line, re.I):
            vals = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line.split(':', 1)[-1])
            if vals: cgst_rows.append([float(x.replace(',', '')) for x in vals])
        elif re.search(r'^\s*SGST\s*@', line, re.I):
            vals = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line.split(':', 1)[-1])
            if vals: sgst_rows.append([float(x.replace(',', '')) for x in vals])
    pcg = cgst_rows[0][0] if cgst_rows and cgst_rows[0] else None
    lcg = cgst_rows[0][-1] if cgst_rows and len(cgst_rows[0]) >= 2 else None
    psg = sgst_rows[0][0] if sgst_rows and sgst_rows[0] else None
    lsg = sgst_rows[0][-1] if sgst_rows and len(sgst_rows[0]) >= 2 else None
    cgst_total = sum((r[0] + r[-1]) if len(r) >= 2 else r[0] for r in cgst_rows) if cgst_rows else None
    sgst_total = sum((r[0] + r[-1]) if len(r) >= 2 else r[0] for r in sgst_rows) if sgst_rows else None

    # Prefer the explicit Net Bill Amount row, never the last random number in Gate Pass.
    total = None
    for line in lines:
        if re.search(r'Net\s+Bill\s+Amount\s*\(\s*Rounded\s*\)', line, re.I) or re.search(r'Net\s+Bill\s+Amount', line, re.I):
            vals = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line.split(':', 1)[-1])
            if vals:
                total = float(vals[-1].replace(',', ''))
                break
    if total is None:
        # Fallback: Gate Pass row with Bill No./Bill Date/Amount columns.
        for line in lines:
            if re.search(r'\bJC\d+\s+BC[/\d]+\s+\d{2}-[A-Z]{3}-\d{2}\s+', line, re.I):
                vals = re.findall(r'(?<![\w.])(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}(?!\d)', line)
                if vals:
                    total = float(vals[-1].replace(',', ''))
                    break

    # Coordinate-based PDF pass: preserves Parts/Labour columns even when PDF text extraction
    # returns the rightmost column before the leftmost column.
    if f.name.lower().endswith('.pdf'):
        try:
            pdf = fitz.open(stream=f.getvalue(), filetype='pdf')
            for page in pdf:
                words = page.get_text('words')
                alltext = ' '.join(w[4] for w in words)
                if 'Net' not in alltext or 'Bill' not in alltext or 'Sub' not in alltext:
                    continue
                # Build y-bands from word coordinates. Values are assigned by x-position:
                # Parts taxable amount is the left amount column (~x=600), Labour is right (~x=770).
                def band_words(y, tol=2.5):
                    return [w for w in words if abs(w[1]-y) <= tol]
                def amount_tokens(ws):
                    return [(w[0], float(w[4].replace(',', ''))) for w in ws if re.fullmatch(r'\d[\d,]*\.\d{2}', w[4])]
                label_y = {}
                for w in words:
                    token = w[4].lower().strip(':')
                    if token == 'amount' and w[1] > 450:
                        pass
                    if token == 'total' and w[1] > 450:
                        pass
                # Detect summary labels and select values within their vertical bands / wrapped lines.
                def find_label_y(pattern):
                    hits = [w for w in words if re.search(pattern, w[4], re.I)]
                    return min((w[1] for w in hits), default=None)
                def nearby_amounts(y, low=0, high=18):
                    if y is None: return []
                    ws = [w for w in words if y-1 <= w[1] <= y+high and w[0] > 550]
                    # Cluster currency words by line, retain first line with relevant monetary values.
                    byline = {}
                    for w in ws:
                        if re.fullmatch(r'\d[\d,]*\.\d{2}', w[4]): byline.setdefault(round(w[1]), []).append(w)
                    return [(x, val) for yy in sorted(byline) for x,val in amount_tokens(byline[yy])]
                # Use summary line y values; the parts amount is the leftmost currency column,
                # labour is the rightmost currency column. Exclude the intermediate zero column.
                ys = [w[1] for w in words if re.search(r'Sub', w[4], re.I) and w[1] > 450]
                ys = sorted(ys)
                if ys:
                    y = ys[0]
                    vals = [(w[0], float(w[4].replace(',', ''))) for w in words if abs(w[1]-y) < 2.5 and re.fullmatch(r'\d[\d,]*\.\d{2}', w[4])]
                    if len(vals) >= 2:
                        vals.sort()
                        parts_before, labour_before = vals[0][1], vals[-1][1]
                dy = find_label_y(r'Discount')
                vals = nearby_amounts(dy, high=10)
                if len(vals) >= 2:
                    vals.sort()
                    parts_disc, labour_disc = vals[0][1], vals[-1][1]
                cy = find_label_y(r'^CGST$'); sy = find_label_y(r'^SGST$')
                cv = nearby_amounts(cy, high=3); sv = nearby_amounts(sy, high=3)
                if len(cv) >= 2:
                    cv.sort(); pcg, lcg = cv[0][1], cv[-1][1]
                if len(sv) >= 2:
                    sv.sort(); psg, lsg = sv[0][1], sv[-1][1]
                cgst_total = (pcg or 0) + (lcg or 0) if pcg is not None and lcg is not None else cgst_total
                sgst_total = (psg or 0) + (lsg or 0) if psg is not None and lsg is not None else sgst_total
                ny = find_label_y(r'Net')
                vals = nearby_amounts(ny, high=5)
                if vals:
                    total = sorted(vals)[-1][1]
                # Supplier name from the signature block, explicitly excluding the customer name.
                for w in words:
                    if w[4].lower() == 'for' and w[1] > 500:
                        same = [x for x in words if abs(x[1]-w[1]) < 3 and x[0] >= w[0]]
                        same.sort()
                        candidate = ' '.join(x[4] for x in same)
                        candidate = re.sub(r'^For\s+', '', candidate, flags=re.I).strip(' .,:;')
                        if len(candidate) >= 8:
                            supplier = candidate
                            break
                break
        except Exception:
            pass

    special = extract_non_fort_summary(text, lines)
    if special.get('supplier'):
        supplier = special['supplier']
    if special.get('inv'):
        inv = special['inv']
    if special.get('inv_date'):
        inv_date = special['inv_date']
    if special.get('vehicle'):
        vehicle = special['vehicle']
    for key in ['parts_before','parts_disc','labour_before','labour_disc','pcg','lcg','psg','lsg','cgst_total','sgst_total','total']:
        if special.get(key) is not None:
            if key == 'parts_before': parts_before = special[key]
            elif key == 'parts_disc': parts_disc = special[key]
            elif key == 'labour_before': labour_before = special[key]
            elif key == 'labour_disc': labour_disc = special[key]
            elif key == 'pcg': pcg = special[key]
            elif key == 'lcg': lcg = special[key]
            elif key == 'psg': psg = special[key]
            elif key == 'lsg': lsg = special[key]
            elif key == 'cgst_total': cgst_total = special[key]
            elif key == 'sgst_total': sgst_total = special[key]
            elif key == 'total': total = special[key]

    gstin = first_match([r'(?i)Dealer\s+GSTIN\s*:\s*([0-9A-Z]{15})', r'(?i)GSTIN\s*[:\-]?\s*([0-9A-Z]{15})'], text)
    pan = first_match([r'(?i)\bPAN\s*[:\-]?\s*([A-Z]{5}\d{4}[A-Z])\b'], text)
    job = first_match([r'(?i)Job\s*Card\s*No\.?\s*:\s*([A-Z0-9/-]+)'], text)
    irn = first_match([r'(?i)\bIRN\s*:\s*([a-f0-9]{32,})'], text)

    review = []
    if not inv: review.append('Invoice number not found')
    if total is None: review.append('Net Bill Amount not found')
    if not inv_date: review.append('Invoice date not found')
    if not vehicle: review.append('Vehicle registration not found')
    if not supplier: review.append('Supplier name not found')
    if parts_before is None or labour_before is None: review.append('Parts/labour split not confidently detected')
    if pcg is None or lcg is None or psg is None or lsg is None: review.append('Parts/labour GST split not confidently detected')
    if total is not None and None not in (parts_before, labour_before, pcg, lcg, psg, lsg):
        expected = (parts_before or 0) - (parts_disc or 0) + (labour_before or 0) - (labour_disc or 0) + (pcg or 0) + (lcg or 0) + (psg or 0) + (lsg or 0)
        if abs(expected - total) > 1.5:
            review.append(f'Amount reconciliation difference ₹{expected-total:,.2f}')

    return {
        'Source File Name': f.name, 'Extraction Method': method, 'Supplier Name': supplier,
        'Receiver': 'SAMVREEDDHI MOBILITY PRIVATE LIMITED', 'Invoice Number': inv,
        'Invoice Date': inv_date, 'Vehicle Registration': vehicle, 'Job Card Number': job,
        'Supplier GSTIN': gstin, 'Supplier PAN': pan, 'IRN': irn,
        'Parts Subtotal Before Discount': parts_before, 'Parts Discount': parts_disc,
        'Labour Subtotal Before Discount': labour_before, 'Labour Discount': labour_disc,
        'Net Labour Cost Before GST': (labour_before - (labour_disc or 0)) if labour_before is not None else None,
        'TDS Rate': 2.0,
        'TDS Amount (2% of Net Labour)': round(max(0, (labour_before or 0) - (labour_disc or 0)) * 0.02, 2) if labour_before is not None else None,
        'Parts CGST': pcg, 'Labour CGST': lcg, 'Parts SGST': psg, 'Labour SGST': lsg,
        'CGST Found Total': cgst_total, 'SGST Found Total': sgst_total,
        'Invoice Gross Total': total, 'Review Status': 'REVIEW REQUIRED' if review else 'EXTRACTED - VERIFY',
        'Review Notes': ' | '.join(review), 'Extracted Text': text
    }

if uploads:
    with st.spinner("Reading invoices and extracting fields..."):
        records=[extract_invoice(f) for f in uploads]
    df=pd.DataFrame(records)
    st.subheader("1. Extraction summary")
    c1,c2,c3=st.columns(3)
    c1.metric("Files uploaded",len(df))
    c2.metric("Invoice numbers found",int(df['Invoice Number'].fillna('').astype(str).str.strip().ne('').sum()))
    c3.metric("Gross totals found",int(df['Invoice Gross Total'].notna().sum()))
    st.warning("Review every invoice before accounting. The app does not silently guess missing amounts. Fields marked REVIEW REQUIRED need manual verification.")
    hidden=['Extracted Text']
    show_cols=[c for c in df.columns if c not in hidden]
    editable=st.data_editor(df[show_cols],use_container_width=True,num_rows='dynamic',column_config={
        'Invoice Gross Total':st.column_config.NumberColumn(format='₹ %.2f'),
        'Parts Subtotal Before Discount':st.column_config.NumberColumn(format='₹ %.2f'),
        'Parts Discount':st.column_config.NumberColumn(format='₹ %.2f'),
        'Labour Subtotal Before Discount':st.column_config.NumberColumn(format='₹ %.2f'),
        'Labour Discount':st.column_config.NumberColumn(format='₹ %.2f')
    })
    with st.expander("Show raw extracted text per invoice"):
        for rec in records:
            st.markdown(f"**{rec['Source File Name']}** — {rec['Extraction Method']}")
            st.text(rec['Extracted Text'][:20000] or 'No readable text extracted.')
    st.subheader("2. Export reviewed extraction")
    st.caption("Exports one row per invoice, including source filename, invoice number, gross amount, components and review notes. Component values are not automatically approved for posting.")
    if st.button("Prepare Excel export",type="primary"):
        out=io.BytesIO()
        tally_rows=[]
        def num(row,key):
            v=row.get(key,None)
            try:
                if pd.isna(v) or v=='': return 0.0
                return float(v)
            except (TypeError,ValueError): return 0.0
        for _,row in editable.iterrows():
            inv=str(row.get('Invoice Number','') or '')
            invdate=str(row.get('Invoice Date','') or '')
            vehicle=str(row.get('Vehicle Registration','') or '')
            supplier=str(row.get('Supplier Name','') or 'REVIEW REQUIRED')
            source=str(row.get('Source File Name','') or '')
            p=num(row,'Parts Subtotal Before Discount'); pdsc=num(row,'Parts Discount')
            l=num(row,'Labour Subtotal Before Discount'); ldsc=num(row,'Labour Discount')
            pcg=num(row,'Parts CGST'); lcg=num(row,'Labour CGST')
            psg=num(row,'Parts SGST'); lsg=num(row,'Labour SGST')
            gross=num(row,'Invoice Gross Total')
            net_labour=max(0.0, l-ldsc)
            tds_amount=round(net_labour*0.02, 2)
            supplier_payable=round(gross-tds_amount, 2)
            narration=f"{source} | Receiver: SAMVREEDDHI MOBILITY PRIVATE LIMITED"
            rows=[
                ('Vehicle R&M_MUM',p,pdsc,'Dr',vehicle,narration),
                ('Vehicle Labour Cost_MUM',l,ldsc,'Dr',vehicle,narration),
                ('Input CGST_MUM',pcg+lcg,0,'Dr','',narration),
                ('Input SGST_MUM',psg+lsg,0,'Dr','',narration),
                (supplier,supplier_payable,0,'Cr','',narration),
                ('TDS Payable - Section 194C',tds_amount,0,'Cr','',narration),
            ]
            for ledger,subtotal,discount,dc,cost,narr in rows:
                tally_rows.append({'Voucher Name':ledger,'Voucher Number':1,'Entry Date':pd.Timestamp.today().date(),'Reference Number/Invoice Number':inv,'Invoice Date':invdate,'Sub Total':subtotal,'Discount':discount,'Net Amount':subtotal-discount,'Debit/Credit':dc,'Cost Centre':cost,'Voucher Narration':narr,'Review Status':row.get('Review Status','REVIEW REQUIRED')})
        with pd.ExcelWriter(out,engine='openpyxl') as writer:
            editable.to_excel(writer,index=False,sheet_name='Invoice Register')
            pd.DataFrame(tally_rows).to_excel(writer,index=False,sheet_name='Tally Entry')
            pd.DataFrame([{'Source File Name':r['Source File Name'],'Extracted Text':r['Extracted Text']} for r in records]).to_excel(writer,index=False,sheet_name='Raw Extracted Text')
        st.download_button("Download Excel (Invoice Register + Tally Entry + Raw Text)",data=out.getvalue(),file_name='Maintenance_Invoice_Extracted_Register.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
else:
    st.info("Upload one or more PDF/image invoices. For scanned files, install Tesseract OCR and confirm its path in the sidebar.")
