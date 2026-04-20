# REST API Documentation

## Overview

The Amex Platinum Dining Map API provides programmatic access to all dining venues, properties, and locations.

**Base URL**: `http://localhost:8001/api/v1`

## Running the API

```bash
pip install fastapi uvicorn
python3 api.py
```

The API will be available at `http://localhost:8001`
Interactive docs at `http://localhost:8001/docs`

## Endpoints

### Health Check
```
GET /api/v1/health
```
Returns API status and data counts.

### Dining Venues
```
GET /api/v1/dining
```

**Query Parameters**:
- `search` (string) — Search by name, cuisine, city
- `country` (string) — Filter by country code
- `cuisine` (string) — Filter by cuisine type
- `min_rating` (float) — Minimum Google rating (3.0-5.0)
- `limit` (int) — Results per page (1-1000, default 100)
- `skip` (int) — Pagination offset (default 0)

**Example**:
```bash
curl "http://localhost:8001/api/v1/dining?country=Japan&cuisine=Sushi&min_rating=4.0&limit=50"
```

### Plat Stays Properties
```
GET /api/v1/stays
```

**Query Parameters**:
- `search` (string) — Search by property name, city, country
- `country` (string) — Filter by country
- `min_rating` (float) — Minimum Google rating
- `limit` (int) — Results per page
- `skip` (int) — Pagination offset

### Love Dining Singapore
```
GET /api/v1/love-dining
```

**Query Parameters**:
- `search` (string) — Search by venue, cuisine, hotel
- `cuisine` (string) — Filter by cuisine
- `venue_type` (string) — "restaurant" or "hotel"
- `min_rating` (float) — Minimum Google rating
- `limit` (int) — Results per page
- `skip` (int) — Pagination offset

### Global Search
```
GET /api/v1/search
```

**Query Parameters**:
- `q` (string, required) — Search query
- `limit` (int) — Max results per dataset (1-500, default 50)

**Example**:
```bash
curl "http://localhost:8001/api/v1/search?q=Michelin&limit=20"
```

Returns results from all three datasets (dining, stays, love_dining).

### Export as CSV
```
GET /api/v1/export/csv
```

**Query Parameters**:
- `dataset` (string, required) — "dining", "stays", or "love_dining"
- `search` (string, optional) — Apply search filter before export
- `country` (string, optional) — Filter by country
- `cuisine` (string, optional) — Filter by cuisine (dining only)

**Example**:
```bash
curl "http://localhost:8001/api/v1/export/csv?dataset=dining&country=Japan" > japan-dining.csv
```

### Statistics
```
GET /api/v1/stats
```

Returns counts and metadata for all datasets.

## Response Format

All endpoints return JSON responses:

```json
{
  "total": 100,
  "limit": 50,
  "skip": 0,
  "results": [
    {
      "id": "venue-123",
      "name": "Restaurant Name",
      "country": "Japan",
      "city": "Tokyo",
      "cuisine": "Sushi",
      "rating": 4.5,
      "lat": 35.6762,
      "lng": 139.7674,
      ...
    }
  ]
}
```

## Authentication

Currently no authentication is required. For production deployment, add API key validation:

```python
from fastapi import Depends, HTTPException, Header

async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != os.getenv("API_KEY"):
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key
```

## Rate Limiting

For production, add rate limiting:

```bash
pip install slowapi
```

Then apply to routes to prevent abuse.

## CORS

CORS is enabled for all origins. For production, restrict to your domain:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],
    ...
)
```

## Deployment

### Vercel
```bash
pip install vercel
vercel --prod
```

### Heroku
```bash
git push heroku main
```

### Docker
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "api:app", "--host", "0.0.0.0"]
```

## Examples

### Get all Michelin restaurants
```bash
curl "http://localhost:8001/api/v1/dining?search=Michelin"
```

### Get 4.5+ star restaurants in Japan
```bash
curl "http://localhost:8001/api/v1/dining?country=Japan&min_rating=4.5"
```

### Get all Love Dining restaurants (not hotels)
```bash
curl "http://localhost:8001/api/v1/love-dining?venue_type=restaurant"
```

### Export all French restaurants
```bash
curl "http://localhost:8001/api/v1/export/csv?dataset=dining&country=France" > france-dining.csv
```

### Search across everything
```bash
curl "http://localhost:8001/api/v1/search?q=sushi&limit=30"
```

## Rate Limits

- No hard rate limit currently
- For production, recommend: 100 req/min per IP or API key

## Support

For issues or feature requests, check the interactive docs at `/docs`

