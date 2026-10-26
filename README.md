Maintenance Invoice Automation Dashboard

A Python and Streamlit application intended to help the operations/accounts team process vehicle maintenance invoices and prepare structured Excel output for review and Tally-oriented entry.
Important: Treat extracted values as a draft, not as verified accounting data. Always compare the generated output with the original supplier invoice and resolve flagged or unexplained differences before posting entries to Tally or using the data for payment.

Overview
The application is designed to help standardize invoice information across vehicle maintenance vendors, including invoices with different layouts. Depending on the invoice and the current application configuration, extraction may use PDF text and/or OCR.

The target workflow is to:
1. Open the dashboard in a browser.
2. Upload maintenance invoice PDF files using the controls provided by the app.
3. Review the extracted invoice and accounting fields.
4. Check missing fields, amount differences, and other exceptions against the source invoice.
5. Export the reviewed data to Excel in the configured Tally-oriented format.
Target data fields and accounting rules
The output is intended to organize invoice details such as:
- Supplier/vendor name
- Invoice/reference number and invoice date
- Vehicle registration number (cost centre)
- Parts cost, net of the applicable parts discount and before GST
- Labour cost, net of the applicable labour discount and before GST
- Combined CGST and SGST amounts for parts and labour
- TDS under Section 194C at the configured 2% rate on net labour cost before GST, where applicable
- Vendor payable amount after deducting TDS
- Configured ledger/voucher names, such as vehicle repair and maintenance, vehicle labour cost, Input CGST, Input SGST, and TDS 194C
The receiver/company field is intended to use Samvreeddhi Mobility Private Limited, as configured for the workflow.


These are target rules for review; confirm that the installed application applies them correctly for each vendor invoice type and for any exceptions such as rounding, credit notes, different tax treatments, or missing invoice details.
Technology
- Python
- Streamlit for the web interface
- Pandas for tabular data handling
- PyMuPDF (fitz) for PDF processing
- Pillow (PIL) for image handling
- NumPy and other packages required by the application
- Tesseract OCR may be required for scanned-document OCR, depending on the current application configuration
Use the dependency versions supplied with the project (for example, in requirements.txt) where available. The packages and OCR configuration should be tested together before setting up the application on another computer.
Requirements
- Windows is the current documented environment.
- Python 3.13, matching the environment in which the app was last run successfully.
- The project source file: maintenance_invoice_dashboard_app.py
- The dependencies used by the project, preferably recorded in requirements.txt.
- If OCR is enabled, the required Tesseract OCR installation and a valid executable path configured in the application.
Run locally on Windows
Open the project folder in VS Code, then open Terminal → New Terminal.
1. Activate the existing virtual environment
.\.venv\Scripts\Activate.ps1
If PowerShell blocks activation, you can allow scripts for the current terminal process only and then activate the environment:
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
.\.venv\Scripts\Activate.ps1
This execution-policy setting applies only to the current PowerShell process. Follow your company's IT/security policy if it restricts script execution.
2. Install dependencies if setting up a new environment
If the repository includes requirements.txt, run:
python -m pip install -r requirements.txt
Do not copy the .venv folder from one computer to another. Create a fresh virtual environment and install the project's recorded dependencies. If requirements.txt is not included, prepare and test a dependency file from the working environment before setting up the app on another computer.
3. Start the dashboard
python -m streamlit run .\maintenance_invoice_dashboard_app.py --server.port 8502 --server.headless true --browser.gatherUsageStats false
Open this address in your browser:
http://localhost:8502
Keep the terminal running while using the dashboard. To stop the server, focus the terminal and press Ctrl+C.
Recommended invoice review checklist
Before accepting an exported row or workbook, compare it with the source invoice:
- Supplier, invoice number, and invoice date match the document.
- Vehicle registration/cost centre is correct.
- Parts and labour have been separated correctly.
- Discounts have been applied to the correct category.
- Taxable amounts and CGST/SGST agree with the invoice.
- TDS is calculated on the applicable net labour amount, before GST, where relevant.
- Vendor payable agrees with the invoice total less applicable TDS and any documented adjustments.
- Rounding differences, blank fields, unreadable text, and missing values are investigated rather than treated as valid zero amounts.
- Ledger names and the final Excel column layout match the company's approved Tally process.
Do not use an extracted value merely because it appears in the spreadsheet. Source documents take precedence when resolving discrepancies.
Repository and data security
This project may process supplier invoices and business financial information. Follow company data-handling rules:
- Keep the GitHub repository private unless the company explicitly authorizes public release.
- Do not commit supplier invoice PDFs, customer/vendor financial records, generated accounting workbooks, or other confidential business data.
- Do not commit .venv/, credentials, API keys, access tokens, passwords, or .streamlit/secrets.toml.
- Store sensitive files only in company-approved locations and use approved access controls.
- Use individual GitHub accounts and organization membership rather than sharing account passwords.
A .gitignore file helps prevent accidental commits, but it is not a substitute for reviewing the staged file list before pushing.
Troubleshooting
NumPy import is blocked by Windows
If the terminal reports an error such as An Application Control policy has blocked this file while importing NumPy, Windows application-control policy is blocking a compiled package file. This is not necessarily an issue with the application source. Follow company IT/security guidance; do not bypass organizational security policy without authorization.
The browser cannot open the dashboard
- Confirm the Streamlit command completed and the terminal still shows a local URL.
- Open http://localhost:8502 on the same computer running the app.
- Check whether another process is already using port 8502; if so, stop that process or use a different port.
Extraction is incomplete or amounts do not reconcile
- Check the invoice PDF is readable and the correct pages were uploaded.
- For scanned PDFs, confirm the configured OCR engine is installed and its path is correct.
- Verify extracted values against the original invoice and flag any unresolved discrepancies.
- Do not post unverified totals into accounting systems.
Source file
The main application entry point is maintenance_invoice_dashboard_app.py.
Status
Internal company tool. Review, test, and approve changes before using the application for production accounting work.
