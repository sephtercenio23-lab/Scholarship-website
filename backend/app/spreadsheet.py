from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

MIN_COLUMN_WIDTH = 10
MAX_COLUMN_WIDTH = 55

CONTENT_TYPES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "</Types>"
)

ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/>'
    "</Relationships>"
)

WORKBOOK_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Applications" sheetId="1" r:id="rId1"/></sheets>'
    "</workbook>"
)

WORKBOOK_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    "</Relationships>"
)

STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    "</fonts>"
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    "</fills>"
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    "</cellXfs>"
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    "</styleSheet>"
)


def clean_cell(value):
    text = "" if value is None else str(value)
    return "".join(char for char in text if char == "\t" or ord(char) >= 32)


def column_letter(index):
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def column_widths(headers, rows):
    widths = []
    for index, header in enumerate(headers):
        longest = len(clean_cell(header))
        for row in rows:
            longest = max(longest, len(clean_cell(row[index])))
        widths.append(max(MIN_COLUMN_WIDTH, min(MAX_COLUMN_WIDTH, longest + 2)))
    return widths


def sheet_cell(reference, value, style=None):
    attributes = f'r="{reference}"'
    if style is not None:
        attributes += f' s="{style}"'
    return (
        f"<c {attributes} t=\"inlineStr\"><is><t xml:space=\"preserve\">"
        f"{escape(clean_cell(value))}</t></is></c>"
    )


def sheet_xml(headers, rows):
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(column_widths(headers, rows), start=1)
    )
    header_cells = "".join(
        sheet_cell(f"{column_letter(index)}1", header, style=1)
        for index, header in enumerate(headers, start=1)
    )
    body_rows = []
    for row_number, row in enumerate(rows, start=2):
        cells = "".join(
            sheet_cell(f"{column_letter(index)}{row_number}", value)
            for index, value in enumerate(row, start=1)
        )
        body_rows.append(f'<row r="{row_number}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetViews><sheetView workbookViewId=\"0\">"
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        "</sheetView></sheetViews>"
        f"<cols>{columns}</cols>"
        f'<sheetData><row r="1">{header_cells}</row>{"".join(body_rows)}</sheetData>'
        "</worksheet>"
    )


def build_xlsx(headers, rows):
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES_XML)
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS_XML)
        archive.writestr("xl/styles.xml", STYLES_XML)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml(headers, rows))
    return buffer.getvalue()
