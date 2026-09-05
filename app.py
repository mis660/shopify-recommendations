import pickle
from fastapi import FastAPI
import uvicorn

app = FastAPI()

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
        # Check if the loaded file is a dictionary (a lookup table)
        if isinstance(recommendation_model, dict):
            
            # 1. Try looking up the exact product ID text
            recommendations = recommendation_model.get(product_id)
            
            # 2. If not found, try looking it up as an integer (number)
            if recommendations is None and product_id.isdigit():
                recommendations = recommendation_model.get(int(product_id))
                
            # 3. If it's still not found, tell the user
            if recommendations is None:
                return {
                    "status": "not_found", 
                    "message": f"Product ID {product_id} does not exist in the .pkl file."
                }
                
            return {
                "status": "success",
                "product_id": product_id,
                "recommended_product_ids": list(recommendations)
            }
        else:
            return {"error": "The .pkl file is a different format we haven't guessed yet."}
            
    except Exception as e:
        return {"error": f"Something went wrong processing the model: {str(e)}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)