# StackBridge-MCP AST Extraction Specification

This document defines the Tree-sitter query patterns and data structures used by StackBridge to extract cross-stack contracts without executing runtime imports or depending on heavy LSP daemons.

---

## 1. Frontend Parser Specification (`TypeScriptFetchParser`)

### Supported Patterns
- `fetch("/api/v1/users/" + userId + "/billing", ...)`
- ``fetch(`/api/v1/users/${userId}/billing`, ...)``
- `axios.get("/api/v1/teams")`, `axios.post(...)`, `apiClient.get(...)`
- `useQuery({ queryKey: [...], queryFn: () => fetch(...) })`

### Extracted Schema (`FrontendEndpointCall`)
```json
{
  "file_path": "frontend/UserProfile.tsx",
  "line_number": 14,
  "http_method": "GET",
  "raw_url": "/api/v1/users/${userId}/billing",
  "normalized_path": "/api/v1/users/{userId}/billing",
  "is_template": true,
  "path_params": ["userId"],
  "query_params": []
}
```

---

## 2. Backend Route Parser Specification (`PythonRouteParser`)

### Supported Patterns
- `@app.get("/api/v1/teams", response_model=List[TeamOut])`
- `@router.get("/users/{user_id}/billing")`
- Sub-router prefix chaining: `app.include_router(billing_router, prefix="/api/v1")`

### Extracted Schema (`BackendRoute`)
```json
{
  "file_path": "backend/routes.py",
  "line_number": 28,
  "function_name": "get_user_billing",
  "raw_path": "/api/v1/users/{user_id}/billing",
  "normalized_path": "/api/v1/users/{user_id}/billing",
  "http_methods": ["GET"],
  "path_params": [{"name": "user_id", "type_hint": "int"}],
  "response_model": "BillingAccountOut",
  "orm_models_referenced": ["BillingAccount"]
}
```

---

## 3. Database ORM Parser Specification (`SQLAlchemyParser`)

### Supported Patterns
- Declarative SQLAlchemy models inheriting from `Base` or `DeclarativeBase`
- `Column(String, nullable=False)`
- `relationship("BillingAccount", back_populates="user")`

### Extracted Schema (`ORMModel`)
```json
{
  "file_path": "backend/models.py",
  "line_number": 12,
  "class_name": "BillingAccount",
  "table_name": "billing_accounts",
  "fields": [
    {"name": "id", "type_str": "Integer", "is_primary_key": true},
    {"name": "user_id", "type_str": "Integer", "is_foreign_key": true},
    {"name": "plan", "type_str": "String", "nullable": false}
  ],
  "relationships": ["User"]
}
```

---

## 4. Route Matching Logic (`RouteMatcher`)

- **Exact Static Match**: `Confidence: 1.0` (Identical normalized path strings).
- **Template Parameter Match**: `Confidence: 0.88 - 0.95` (Segments align with dynamic variables, e.g., `{userId}` ↔ `{user_id}`).
- **Fuzzy Segment Alignment**: `Confidence: 0.50 - 0.75` (Prefix/suffix match with minor parameter variations).
