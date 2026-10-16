from app.database import get_db
from datetime import datetime

async def generate_fhir_codesystem() -> dict:
    db = get_db()
    collection = db["namaste_codes"]
    cursor = collection.find({}, {"_id": 0})
    codes = await cursor.to_list(length=10000)

    concepts = []
    for code in codes:
        concepts.append({
            "code": code["namaste_code"],
            "display": code["term_english"],
            "definition": code["term_original"],
            "property": [
                {"code": "system", "valueString": code["system"]},
                {"code": "category", "valueString": code["category"]},
                {"code": "mapping_status", "valueString": code["mapping_status"]}
            ]
        })

    return {
        "resourceType": "CodeSystem",
        "id": "namaste-codesystem",
        "url": "https://namaste.ayush.gov.in/fhir/CodeSystem/namaste",
        "version": "1.0.0",
        "name": "NAMASTECodeSystem",
        "title": "National AYUSH Morbidity and Standardized Terminologies Electronic (NAMASTE)",
        "status": "active",
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "publisher": "Ministry of Ayush, Government of India",
        "description": "Standardized terminology codes for Ayurveda, Siddha and Unani systems of medicine",
        "count": len(concepts),
        "property": [
            {"code": "system", "type": "string", "description": "ASU system"},
            {"code": "category", "type": "string", "description": "Disease category"},
            {"code": "mapping_status", "type": "string", "description": "ICD-11 mapping status"}
        ],
        "concept": concepts
    }

async def generate_fhir_conceptmap() -> dict:
    db = get_db()
    collection = db["namaste_codes"]
    cursor = collection.find({"mapping_status": {"$in": ["partial", "complete"]}}, {"_id": 0})
    mapped = await cursor.to_list(length=10000)

    elements = []
    for code in mapped:
        targets = []
        if code.get("icd_biomedicine_code"):
            targets.append({
                "code": code["icd_biomedicine_code"],
                "display": code.get("icd_biomedicine_display", ""),
                "equivalence": "equivalent",
                "comment": f"Confidence: {code.get('confidence_score', 'N/A')}"
            })
        if code.get("tm2_code"):
            targets.append({
                "code": code["tm2_code"],
                "display": code.get("tm2_display", ""),
                "equivalence": "equivalent",
                "comment": "ICD-11 TM2 Chapter 26"
            })
        if targets:
            elements.append({
                "code": code["namaste_code"],
                "display": code["term_english"],
                "target": targets
            })

    return {
        "resourceType": "ConceptMap",
        "id": "namaste-to-icd11",
        "url": "https://namaste.ayush.gov.in/fhir/ConceptMap/namaste-to-icd11",
        "version": "1.0.0",
        "name": "NAMASTEToICD11",
        "title": "NAMASTE to ICD-11 ConceptMap",
        "status": "active",
        "date": datetime.utcnow().strftime("%Y-%m-%d"),
        "publisher": "Ministry of Ayush, Government of India",
        "sourceUri": "https://namaste.ayush.gov.in/fhir/CodeSystem/namaste",
        "targetUri": "http://hl7.org/fhir/sid/icd-11",
        "group": [
            {
                "source": "https://namaste.ayush.gov.in/fhir/CodeSystem/namaste",
                "target": "http://hl7.org/fhir/sid/icd-11",
                "element": elements
            }
        ]
    }
