# Surface

## Input Shape Catalog

### IS-001

- URL pattern: POST /api/workflow/approve
- Client-controlled params: docId, status
- State transition: draft -> approved
- Linked threat hypothesis: H-001

## Permission / State Working Matrix

| Front | Action/request | Role A expected | Role B observed E-id | State edge | Next control |
|---|---|---|---|---|---|
| F-001 | POST /api/workflow/approve status=approved | reviewer-only | E-001 | State edge: draft -> approved | replay as submitter |
