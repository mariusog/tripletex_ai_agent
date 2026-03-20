# Tripletex API v2 Reference

## Base URL & Authentication

- **Base URL:** Use the `base_url` from `tripletex_credentials` (in competition) or `https://kkpqfuj-amager.tripletex.dev/v2` (sandbox)
- **Auth:** Basic Auth with username `0`, password = session token
- **OpenAPI spec:** Available at `/v2/openapi.json`

## Response Formats

### List Response
```json
{
  "fullResultSize": 42,
  "from": 0,
  "count": 20,
  "versionDigest": "string",
  "values": [...]
}
```

### Single Object Response
```json
{
  "value": { ... }
}
```

### Error Response
```json
{
  "status": 400,
  "code": 4000,
  "message": "Description",
  "developerMessage": "Technical details",
  "validationMessages": [
    {"field": "name", "message": "Required"}
  ],
  "requestId": "x-tlx-request-id"
}
```

## Common Query Parameters

| Parameter | Description |
|-----------|-------------|
| `fields` | Field selection: `id,name`, `*`, `project(name)`, `project(*)` |
| `from` | Pagination offset (default 0) |
| `count` | Page size (default 20) |
| `sorting` | Sort order: `date`, `-date` (descending), `project.name,-date` |

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 204 | No Content |
| 400 | Bad Request |
| 401 | Unauthorized |
| 403 | Forbidden |
| 404 | Not Found |
| 409 | Conflict |
| 422 | Validation Error |
| 429 | Rate Limited |
| 500 | Internal Error |

## Rate Limiting Headers

- `X-Rate-Limit-Limit` - Max allowed requests
- `X-Rate-Limit-Remaining` - Remaining requests
- `X-Rate-Limit-Reset` - Seconds until reset

---

## Key Endpoints for Competition Tasks

### Employee

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/employee` | Search employees |
| GET | `/employee/{id}` | Get by ID |
| POST | `/employee` | Create employee |
| PUT | `/employee/{id}` | Update employee |
| DELETE | `/employee/{id}` | Delete employee |
| POST | `/employee/list` | Create multiple |

**Key fields:** `firstName`, `lastName`, `email`, `phoneNumberMobile`, `department`, `employments`, `roles`

### Customer

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/customer` | Search customers |
| GET | `/customer/{id}` | Get by ID |
| POST | `/customer` | Create customer |
| PUT | `/customer/{id}` | Update customer |
| DELETE | `/customer/{id}` | Delete customer |
| POST | `/customer/list` | Create multiple |

**Key fields:** `name`, `email`, `phoneNumber`, `organizationNumber`, `invoiceEmail`, `deliveryAddress`

### Product

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/product` | Search products |
| GET | `/product/{id}` | Get by ID |
| POST | `/product` | Create product |
| PUT | `/product/{id}` | Update product |
| DELETE | `/product/{id}` | Delete product |

**Key fields:** `name`, `number`, `costExcludingVatCurrency`, `priceExcludingVatCurrency`, `priceIncludingVatCurrency`, `vatType`, `account`, `department`

### Invoice

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/invoice` | Search invoices |
| GET | `/invoice/{id}` | Get by ID |
| POST | `/invoice` | Create invoice |
| POST | `/invoice/:send` | Send invoice |
| POST | `/invoice/{id}/:createCreditNote` | Create credit note |
| POST | `/invoice/{id}/:payment` | Register payment |

**Key fields:** `invoiceDate`, `invoiceDueDate`, `customer`, `orders`, `lines`, `totalAmount`, `currency`

### Order

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/order` | Search orders |
| GET | `/order/{id}` | Get by ID |
| POST | `/order` | Create order |
| PUT | `/order/{id}` | Update order |

**Key fields:** `customer`, `orderDate`, `deliveryDate`, `orderLines`, `project`, `department`

### Order Line

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/order/orderline` | Search order lines |
| POST | `/order/orderline` | Create order line |
| POST | `/order/orderline/list` | Create multiple |

**Key fields:** `order`, `product`, `description`, `count`, `unitCostCurrency`, `unitPriceExcludingVatCurrency`, `vatType`

### Project

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/project` | Search projects |
| GET | `/project/{id}` | Get by ID |
| POST | `/project` | Create project |
| PUT | `/project/{id}` | Update project |
| DELETE | `/project/{id}` | Delete project |

**Key fields:** `name`, `number`, `projectManager`, `department`, `startDate`, `endDate`, `customer`, `isClosed`, `isInternal`

### Department

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/department` | Search departments |
| GET | `/department/{id}` | Get by ID |
| POST | `/department` | Create department |
| PUT | `/department/{id}` | Update department |

**Key fields:** `name`, `departmentNumber`, `departmentManager`

### Travel Expense

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/travelExpense` | Search travel expenses |
| GET | `/travelExpense/{id}` | Get by ID |
| POST | `/travelExpense` | Create travel expense |
| PUT | `/travelExpense/{id}` | Update travel expense |
| POST | `/travelExpense/:approve` | Approve travel expense |
| POST | `/travelExpense/:deliver` | Deliver travel expense |

**Key fields:** `employee`, `project`, `department`, `travelDetails`, `costs`, `perDiemCompensations`

### Ledger / Voucher

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ledger/voucher` | Search vouchers |
| GET | `/ledger/voucher/{id}` | Get by ID |
| POST | `/ledger/voucher` | Create voucher |
| PUT | `/ledger/voucher/{id}` | Update voucher |
| DELETE | `/ledger/voucher/{id}` | Delete voucher |
| POST | `/ledger/voucher/:reverse` | Reverse voucher |

### Ledger / Account

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ledger/account` | Search accounts |
| GET | `/ledger/account/{id}` | Get by ID |

### Ledger / Posting

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/ledger/posting` | Search postings |

### Bank Reconciliation

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/bank/reconciliation` | Search reconciliations |
| POST | `/bank/reconciliation` | Create reconciliation |
| PUT | `/bank/reconciliation/{id}` | Update reconciliation |
| DELETE | `/bank/reconciliation/{id}` | Delete reconciliation |
| PUT | `/bank/reconciliation/{id}/:adjustment` | Add adjustment |

### Balance Sheet

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/balanceSheet` | Get balance sheet (requires `dateFrom`, `dateTo` in yyyy-MM-dd) |

### Activity

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/activity` | Search activities |
| POST | `/activity` | Create activity |
| GET | `/activity/{id}` | Get by ID |

### Asset

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/asset` | Search assets |
| POST | `/asset` | Create asset |
| GET | `/asset/{id}` | Get by ID |
| PUT | `/asset/{id}` | Update asset |
| DELETE | `/asset/{id}` | Delete asset |

---

## Field Selection Examples

```
# Basic fields
?fields=id,firstName,lastName

# All fields
?fields=*

# Nested object fields
?fields=id,customer(name,email)

# All subfields of a nested object
?fields=*,customer(*)

# Combine
?fields=*,activity(name),employee(*)
```

## Pagination

```
# First 100 results
?from=0&count=100

# Next 100
?from=100&count=100
```

## Special Endpoint Conventions

- Actions prefixed with `:` (e.g., `/:approve`, `/:send`)
- Aggregated results prefixed with `>` (e.g., `/>thisWeeksBillables`)
