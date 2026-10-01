# NAMASTE FHIR Terminology Service

A FHIR R4-compliant terminology microservice that maps India's NAMASTE codes (National AYUSH Morbidity and Standardized Terminologies Electronic) to WHO ICD-11 TM2 and biomedical equivalents — built in response to the Ministry of Ayush + SIH 2025 problem statement.

**Live Demo**: https://namaste-sage.vercel.app  
**API Docs**: https://namaste-fhir-backend.onrender.com/docs

---

## Problem

India has 7 lakh+ registered Ayurveda, Siddha and Unani (ASU) practitioners diagnosing patients daily. Their diagnoses exist only as free text or NAMASTE codes — invisible to:

- Insurance systems (need ICD codes for claims)
- Global health databases (need ICD-11 for reporting)
- ABDM / NHCX (need FHIR R4 for interoperability)

WHO released ICD-11 TM2 (Chapter 26) in February 2025 covering 529 ASU disorder categories — but no production EMR has integrated it. The NAMASTE to ICD-11 mapping pipeline does not exist anywhere.

## Solution

This microservice sits between any Ayurveda EMR and ABDM. It:

1. Ingests all 7,363 NAMASTE codes (Ayurveda, Siddha, Unani) from the official portal
2. Queries WHO ICD-11 API to suggest TM2 + biomedical equivalents
3. Stores mappings with confidence scores in MongoDB
4. Exposes FHIR R4 CodeSystem + ConceptMap endpoints
5. Provides autocomplete REST API for EMR integration

---

## Architecture
```
Ayurveda EMR
     ↓
POST /namaste/search?q=jwara            autocomplete
POST /mapping/suggest/{code}            WHO ICD-11 lookup
GET  /fhir/CodeSystem/namaste           FHIR R4 CodeSystem
GET  /fhir/ConceptMap/namaste-to-icd11  FHIR R4 ConceptMap
     ↓
ABDM / NHCX / Insurance Systems
```

---

## Current Dataset Stats

| Metric | Count |
|--------|-------|
| Total NAMASTE codes | 7,363 |
| Ayurveda codes | 2,919 |
| Siddha codes | 1,923 |
| Unani codes | 2,521 |
| Auto-mapped to ICD-11 | 187 (2.5%) |
| Dual coded (TM2 + Biomedicine) | 21 |
| Pending expert review | 7,176 |

---

## Live Demo Output
```
AYU-0001 Jwara (Fever)
  TM2:        SE31  Growth fever disorder (Chapter 26)
  Biomedicine: MG26  Fever of other or unknown origin
  Status:     complete | Confidence: 100%

AYU-0007 Madhumeha (Diabetes Mellitus)
  Biomedicine: 5A14  Diabetes mellitus, type unspecified
  Status:     partial | Confidence: 100%

AYU-0005 Amavata (Rheumatoid Arthritis)
  Biomedicine: FA20.Z  Rheumatoid arthritis
  Status:     partial | Confidence: 100%
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/health` | Service health check |
| POST | `/admin/ingest` | Ingest NAMASTE CSV into MongoDB |
| POST | `/admin/ingest-xls` | Ingest full XLS dataset |
| GET | `/namaste/search?q=` | Fuzzy search NAMASTE codes |
| GET | `/namaste/code/{code}` | Lookup by NAMASTE code |
| POST | `/mapping/suggest/{code}` | Trigger WHO ICD-11 mapping |
| POST | `/mapping/bulk` | Bulk map unmapped codes |
| GET | `/fhir/CodeSystem/namaste` | FHIR R4 CodeSystem |
| GET | `/fhir/ConceptMap/namaste-to-icd11` | FHIR R4 ConceptMap |
| GET | `/stats/` | Mapping progress stats |

---

## Stack

- **Backend**: FastAPI (Python 3.12) + Motor (async MongoDB)
- **Database**: MongoDB Atlas
- **External API**: WHO ICD-11 API (live, authenticated)
- **Standards**: FHIR R4, ICD-11 TM2, NAMASTE
- **Frontend**: Next.js 16 + Tailwind CSS
- **Infra**: Docker + Docker Compose + Render + Vercel

---

## Quick Start
```bash
# 1. Clone
git clone https://github.com/siddhanthsain/NAMASTE.git
cd NAMASTE/namaste-fhir-service

# 2. Set credentials
cp backend/.env.example backend/.env
# Edit backend/.env with your WHO ICD-11 API credentials
# Get free credentials at: https://icdaccessmanagement.who.int/signup

# 3. Start services
docker compose up --build

# 4. Seed NAMASTE data
curl -X POST http://localhost:8000/admin/ingest

# 5. Test mapping
curl -X POST http://localhost:8000/mapping/suggest/AYU-0007

# 6. Start frontend
cd frontend && npm install && npm run dev
```

---

## Alignment with SIH 2025 Problem Statement

| Requirement | Status |
|-------------|--------|
| NAMASTE CSV ingestion to FHIR CodeSystem | Done |
| WHO ICD-11 TM2 sync via API | Done |
| NAMASTE to TM2 translation operation | Done |
| Autocomplete value-set lookup endpoint | Done |
| FHIR Bundle with dual coding | In progress |
| ABHA OAuth 2.0 | In progress |
| Web interface for search + mapping | Done |
| ICD-11 Coding rules compliance | Done |

---

## Roadmap

- Layer 2: Expert validation UI for crowdsourced ConceptMap completion
- FHIR Bundle upload endpoint with dual coding
- ABHA OAuth 2.0 middleware
- SNOMED CT + LOINC semantic enrichment
- Deployment on NIC cloud / ABDM sandbox

---

## Built By

Siddhanth — Final year B.Tech CS, Arya Institute of Engineering & Technology, Jaipur  
Built as a response to SIH 2025 Problem Statement: Develop API code to integrate NAMASTE and/or ICD-11 via TM2 into existing EMR systems compliant with EHR Standards for India

---

## Relevant Links

- [NAMASTE Portal](https://namaste.ayush.gov.in)
- [WHO ICD-11 TM2](https://icd.who.int/browse/2024-01/mms/en#chapter26)
- [WHO ICD-11 API](https://icdaccessmanagement.who.int)
- [ABDM / NHA](https://abdm.gov.in)
- [India EHR Standards 2016](https://mohfw.gov.in)
