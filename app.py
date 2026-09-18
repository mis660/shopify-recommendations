import os
import time
import pickle
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# Allow your Shopify storefront to call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://pannajewellers.com",
        "https://www.pannajewellers.com",
        "https://pje-2.myshopify.com",
        "https://ksu2nu-1t.myshopify.com",
    ],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# --- Load the recommendation model ---
try:
    with open("model.pkl", "rb") as file:
        recommendation_model = pickle.load(file)
except FileNotFoundError:
    print("Error: model.pkl not found in this folder.")
    recommendation_model = None

# --- Shopify config (from Render environment variables) ---
SHOPIFY_STORE_DOMAIN = os.environ.get("SHOPIFY_STORE_DOMAIN")  # e.g. pje-2.myshopify.com
SHOPIFY_CLIENT_ID = os.environ.get("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.environ.get("SHOPIFY_CLIENT_SECRET")
SHOPIFY_API_VERSION = "2026-07"

TOKEN_URL = f"https://{SHOPIFY_STORE_DOMAIN}/admin/oauth/access_token"
GRAPHQL_URL = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

# In-memory token cache (simple, works fine for a single-instance API)
_token_cache = {"access_token": None, "expires_at": 0}


def get_access_token():
    """Fetch a fresh Admin API access token using the client credentials grant,
    reusing the cached one until it's close to expiring."""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    if not SHOPIFY_STORE_DOMAIN or not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("Missing Shopify env vars: SHOPIFY_STORE_DOMAIN / SHOPIFY_CLIENT_ID / SHOPIFY_CLIENT_SECRET")
        return None

    try:
        response = requests.post(
            TOKEN_URL,
            json={
                "client_id": SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
                "grant_type": "client_credentials",
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        access_token = data.get("access_token")
        expires_in = data.get("expires_in", 3600)  # seconds

        _token_cache["access_token"] = access_token
        _token_cache["expires_at"] = now + expires_in

        return access_token
    except Exception as e:
        print(f"Failed to get Shopify access token: {e}")
        return None


GRAPHQL_QUERY = """
query getVariantByBarcode($query: String!) {
  productVariants(first: 1, query: $query) {
    edges {
      node {
        id
        price
        product {
          id
          title
          handle
          featuredImage {
            url
          }
        }
      }
    }
  }
}
"""


def fetch_shopify_product_by_barcode(barcode: str):
    """Look up a Shopify product using its variant barcode via the Admin GraphQL API."""
    token = get_access_token()
    if not token:
        return None

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": token,
    }
    payload = {
        "query": GRAPHQL_QUERY,
        "variables": {"query": f"barcode:'{barcode}'"},
    }

    try:
        response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            print(f"GraphQL errors for barcode {barcode}: {data['errors']}")
            return None

        edges = (
            data.get("data", {})
            .get("productVariants", {})
            .get("edges", [])
        )
        if not edges:
            return None

        variant = edges[0]["node"]
        product = variant["product"]

        return {
            "title": product["title"],
            "handle": product["handle"],
            "url": f"https://{SHOPIFY_STORE_DOMAIN.replace('.myshopify.com', '')}.com/products/{product['handle']}"
                   if SHOPIFY_STORE_DOMAIN else None,
            "image": product["featuredImage"]["url"] if product.get("featuredImage") else None,
            "price": variant.get("price"),
        }
    except Exception as e:
        print(f"Shopify lookup failed for barcode {barcode}: {e}")
        return None


@app.get("/recommend/{product_id}")
def get_recommendations(product_id: str):
    if recommendation_model is None:
        return {"error": "Model is not loaded."}

    try:
        if not isinstance(recommendation_model, dict):
            return {"error": "The .pkl file is a different format we haven't guessed yet."}

        recommendations = recommendation_model.get(product_id)

        if recommendations is None and product_id.isdigit():
            recommendations = recommendation_model.get(int(product_id))

        if recommendations is None:
            return {
                "status": "not_found",
                "message": f"Product ID {product_id} does not exist in the .pkl file."
            }

        enriched = []
        for rec in recommendations:
            design_no = rec.get("Design No") if isinstance(rec, dict) else rec
            shopify_data = fetch_shopify_product_by_barcode(design_no)

            enriched.append({
                "design_no": design_no,
                "category": rec.get("Category") if isinstance(rec, dict) else None,
                "model_price": rec.get("Price") if isinstance(rec, dict) else None,
                "shopify_product": shopify_data,  # None if not found in Shopify
            })

        return {
            "status": "success",
            "product_id": product_id,
            "recommended_products": enriched
        }

    except Exception as e:
        return {"error": f"Something went wrong processing the model: {str(e)}"}


@app.get("/debug/token")
def debug_token():
    """Temporary endpoint to check if token fetching works. Remove this once everything is confirmed."""
    token = get_access_token()
    if token:
        return {"status": "success", "message": "Access token fetched successfully."}
    return {"status": "failed", "message": "Could not fetch access token. Check Render logs for details."}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
