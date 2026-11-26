from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

MIN_COLUMN_WIDTH = 10
MAX_COLUMN_WIDTH = 55

# Excel stores drawing sizes in English Metric Units: 914400 EMU per inch.
EMU_PER_PIXEL = 9525

DRAWING_NS = (
    'xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
)
RELATIONSHIP_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_DOCUMENT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

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
    "{extra}"
    "</Types>"
)

IMAGE_CONTENT_TYPES = {
    "png": "image/png",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
}
DRAWING_CONTENT_TYPE = (
    '<Override PartName="/xl/drawings/drawing1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
)

ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<Relationships xmlns="{RELATIONSHIP_NS}">'
    '<Relationship Id="rId1" '
    f'Type="{OFFICE_DOCUMENT_REL}/officeDocument" '
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
    f'<Relationships xmlns="{RELATIONSHIP_NS}">'
    '<Relationship Id="rId1" '
    f'Type="{OFFICE_DOCUMENT_REL}/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" '
    f'Type="{OFFICE_DOCUMENT_REL}/styles" '
    'Target="styles.xml"/>'
    "</Relationships>"
)

WORKSHEET_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<Relationships xmlns="{RELATIONSHIP_NS}">'
    '<Relationship Id="rId1" '
    f'Type="{OFFICE_DOCUMENT_REL}/drawing" '
    'Target="../drawings/drawing1.xml"/>'
    "</Relationships>"
)

STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="3">'
    '<font><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="12"/><name val="Calibri"/><family val="2"/></font>'
    '</fonts>'
    '<fills count="2">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    '</fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '</cellXfs>'
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
            if index < len(row):
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


def row_xml(row_number, cells, height=None):
    if not cells and height is None:
        return ""
    attributes = f'r="{row_number}"'
    if height:
        attributes += f' ht="{height}" customHeight="1"'
    return f"<row {attributes}>{cells}</row>"


def sheet_xml(headers, rows, row_heights=None, has_drawing=False):
    row_heights = row_heights or {}
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
        body_rows.append(row_xml(row_number, cells, row_heights.get(row_number - 1)))
    # Blank rows still need an explicit height when a signature image is anchored on them.
    for row_index, height in sorted(row_heights.items()):
        if row_index > len(rows):
            body_rows.append(row_xml(row_index + 1, "", height))
    drawing = '<drawing r:id="rId1"/>' if has_drawing else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'xmlns:r="{OFFICE_DOCUMENT_REL}">'
        "<sheetViews><sheetView workbookViewId=\"0\">"
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        "</sheetView></sheetViews>"
        f"<cols>{columns}</cols>"
        f'<sheetData><row r="1">{header_cells}</row>{"".join(body_rows)}</sheetData>'
        f"{drawing}"
        "</worksheet>"
    )


def image_anchor(index, image):
    """One image anchored to a single cell, sized independently of the cell."""
    width = int(image.get("width") or 120)
    height = int(image.get("height") or 60)
    cx, cy = width * EMU_PER_PIXEL, height * EMU_PER_PIXEL
    return (
        "<xdr:oneCellAnchor>"
        f"<xdr:from><xdr:col>{int(image.get('col', 0))}</xdr:col><xdr:colOff>0</xdr:colOff>"
        f"<xdr:row>{int(image.get('row', 0))}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>"
        f'<xdr:ext cx="{cx}" cy="{cy}"/>'
        "<xdr:pic><xdr:nvPicPr>"
        f'<xdr:cNvPr id="{index}" name="Signature {index}"/>'
        '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>'
        "</xdr:nvPicPr>"
        "<xdr:blipFill>"
        f'<a:blip xmlns:r="{OFFICE_DOCUMENT_REL}" r:embed="rId{index}"/>'
        "<a:stretch><a:fillRect/></a:stretch>"
        "</xdr:blipFill>"
        "<xdr:spPr><a:xfrm>"
        f'<a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/>'
        "</a:xfrm>"
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</xdr:spPr>"
        "</xdr:pic><xdr:clientData/>"
        "</xdr:oneCellAnchor>"
    )


def drawing_xml(images):
    anchors = "".join(
        image_anchor(index, image) for index, image in enumerate(images, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f"<xdr:wsDr {DRAWING_NS}>{anchors}</xdr:wsDr>"
    )


def drawing_rels_xml(images):
    relationships = "".join(
        f'<Relationship Id="rId{index}" Type="{OFFICE_DOCUMENT_REL}/image" '
        f'Target="../media/image{index}.{image_extension(image)}"/>'
        for index, image in enumerate(images, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<Relationships xmlns="{RELATIONSHIP_NS}">{relationships}</Relationships>'
    )


def image_extension(image):
    return str(image.get("extension") or "png").lower()


def content_types_xml(images):
    extensions = {image_extension(image) for image in images}
    extra = "".join(
        f'<Default Extension="{extension}" ContentType="{IMAGE_CONTENT_TYPES.get(extension, "image/png")}"/>'
        for extension in sorted(extensions)
    )
    if images:
        extra += DRAWING_CONTENT_TYPE
    return CONTENT_TYPES_XML.format(extra=extra)


def build_xlsx(headers, rows, images=None, row_heights=None):
    """Build a single-sheet workbook, optionally with images anchored above cells.

    ``images`` entries accept ``data`` (bytes), ``extension`` (png/jpeg),
    ``row``/``col`` (0-based cell) and ``width``/``height`` in pixels.
    ``row_heights`` maps a 0-based row index to a height in points.
    """
    images = list(images or [])
    row_heights = dict(row_heights or {})
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(images))
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", WORKBOOK_XML)
        archive.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS_XML)
        archive.writestr("xl/styles.xml", STYLES_XML)
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            sheet_xml(headers, rows, row_heights=row_heights, has_drawing=bool(images)),
        )
        if images:
            archive.writestr("xl/worksheets/_rels/sheet1.xml.rels", WORKSHEET_RELS_XML)
            archive.writestr("xl/drawings/drawing1.xml", drawing_xml(images))
            archive.writestr("xl/drawings/_rels/drawing1.xml.rels", drawing_rels_xml(images))
            for index, image in enumerate(images, start=1):
                archive.writestr(
                    f"xl/media/image{index}.{image_extension(image)}",
                    image["data"],
                )
    return buffer.getvalue()
