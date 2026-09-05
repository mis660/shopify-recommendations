import pickle
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI()

# Allow your Shopify store to make requests to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all websites to connect
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load the model
try:
    with open("model.pkl", "rb") as file:
        recommendation_model = pickle.load(file)
except FileNotFoundError:
    print("Error: model.pkl not found in this folder.")
    recommendation_model = None

@app.get("/recommend/{product_id}")
def get_recommendations(product_id: str):
    if recommendation_model is None:
        return {"error": "Model is not loaded."}
    
    try:
        if isinstance(recommendation_model, dict):
            recommendations = recommendation_model.get(product_id)
            
            if recommendations is None and product_id.isdigit():
                recommendations = recommendation_model.get(int(product_id))
                
            if recommendations is None:
                return {
                    "status": "not_found", 
                    "message": f"Product ID {product_id} not found in model."
                }
                
            return {
                "status": "success",
                "product_id": product_id,
                "recommended_product_ids": list(recommendations)
            }
        else:
            return {"error": "Model format not recognized."}
            
    except Exception as e:
        return {"error": f"Error: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
