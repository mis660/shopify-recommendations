import os
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

# --- Shopify Admin API config (from Render environment variables) ---
SHOPIFY_STORE_DOMAIN = os.environ.get("SHOPIFY_STORE_DOMAIN")
SHOPIFY_ADMIN_TOKEN = os.environ.get("SHOPIFY_ADMIN_TOKEN")
SHOPIFY_API_VERSION = "2024-01"

GRAPHQL_URL = f"https://{SHOPIFY_STORE_DOMAIN}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"

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
    if not SHOPIFY_STORE_DOMAIN or not SHOPIFY_ADMIN_TOKEN:
        return None

    headers = {
        "Content-Type": "application/json",
        "X-Shopify-Access-Token": SHOPIFY_ADMIN_TOKEN,
    }
    payload = {
        "query": GRAPHQL_QUERY,
        "variables": {"query": f"barcode:'{barcode}'"},
    }

    try:
        response = requests.post(GRAPHQL_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

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

        # 1. Try looking up the exact product ID text
        recommendations = recommendation_model.get(product_id)

        # 2. If not found, try looking it up as an integer (number)
        if recommendations is None and product_id.isdigit():
            recommendations = recommendation_model.get(int(product_id))

        # 3. If still not found, tell the user
        if recommendations is None:
            return {
                "status": "not_found",
                "message": f"Product ID {product_id} does not exist in the .pkl file."
            }

        # 4. Enrich each recommendation with real Shopify product data
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
