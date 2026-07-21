#!/usr/bin/env python3
"""Generate a minimal, valid .docx resume fixture (stdlib zipfile only).

Exists so the onboard-me eval can exercise the '.docx resume' fallback path
(unzip word/document.xml -> clean text) without a poppler/parser dependency.
ponytail: three-part minimal OOXML; add python-docx only if a fixture ever
needs real styling.
"""
import os
import zipfile

PARAS = [
    "TAYLOR MORGAN",
    "San Francisco, CA - taylor.morgan@example.com - portfolio: taylormorgan.design",
    "",
    "SUMMARY",
    "Senior product designer, 7 years, focused on design systems and complex "
    "B2B workflows. Owns product design end to end from discovery to ship and "
    "mentors two mid-level designers. Wants to grow into staff/lead IC design.",
    "",
    "EXPERIENCE",
    "Northwind Software - Senior Product Designer (2021-present)",
    "Built and governs the company design system (120+ components, Figma). "
    "Led redesign of the core analytics workflow; task time down 34 percent. "
    "Runs design critique and mentors two mid-level designers.",
    "Brightline - Product Designer (2018-2021)",
    "Shipped onboarding and billing flows for a B2B SaaS platform. Partnered "
    "with PM and eng on discovery, prototyping, and usability testing.",
    "",
    "EDUCATION",
    "B.F.A. Interaction Design, California College of the Arts (2017)",
    "",
    "SKILLS",
    "Design systems - Figma - prototyping - user research - accessibility - HTML/CSS",
]

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>'
)

RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>'
)


def xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def document_xml() -> str:
    body = []
    for p in PARAS:
        if p:
            body.append(
                "<w:p><w:r><w:t xml:space=\"preserve\">%s</w:t></w:r></w:p>"
                % xml_escape(p)
            )
        else:
            body.append("<w:p/>")
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(body) + "</w:body></w:document>"
    )


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "design_resume.docx")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", document_xml())
    print("wrote", path, os.path.getsize(path), "bytes")
