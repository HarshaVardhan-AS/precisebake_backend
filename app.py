from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from dotenv import load_dotenv
import os
from google import genai  # Import genai library
import json
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address




load_dotenv()
API_KEY = os.getenv("GEMINI_API_KEY")  # Fetch API key from the environment variable

app = Flask(__name__)
CORS(app)

limiter = Limiter(get_remote_address, app=app, default_limits=["10 per minute"],storage_uri="memory://")


client = genai.Client(api_key=API_KEY)
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL") # Fetch Database URL from the environment variable
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class IngredientCategory(db.Model):
    __tablename__ = 'ingredient_categories'
    id = db.Column(db.Integer, primary_key=True)
    category_name = db.Column(db.String(100), nullable=False)

class Ingredient(db.Model):
    __tablename__ = 'ingredients'
    id = db.Column(db.Integer, primary_key=True)
    ingredient_name = db.Column(db.String(100), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('ingredient_categories.id'), nullable=False)
    density_g_ = db.Column(db.Float, nullable=False)
    cup_g = db.Column(db.Float, nullable=False)
    tbsp_g = db.Column(db.Float, nullable=False)
    tsp_g = db.Column(db.Float, nullable=False)

    category = db.relationship('IngredientCategory', backref='ingredients')  # To access category data from Ingredient

@app.route('/')
def home():
    return "Welcome to PreciseBake API!"

@app.route('/convert', methods=['POST'])
@limiter.limit("15 per minute")
def convert():
    converted_ingredients = []  # Store all converted values
    data = request.json
    recipe_text = data.get("text") or data.get("recipeText")

    if not recipe_text:
        return jsonify({"error": "No recipe text provided"}), 400

    try:
        
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"Extract structured ingredient data (name, unit, amount) from: {recipe_text}. "
                     "Ensure the ingredients are food items or items used in cooking and baking, and NOT people, places, or unknown words."
                     "Ignore any such unknown words found entirely."
                     "If **none** of the words in the input are valid food ingredients, return exactly this string: 'Invalid user input' (without quotes)."
                     "Otherwise, return only a JSON list, without explanations or extra text. Example output: "
                     '[{"ingredient": "flour", "unit": "cups", "amount": 2}, '
                     '{"ingredient": "sugar", "unit": "tbsp", "amount": 3}].'
        )


        response_text = response.text.strip()

        if response_text == "Invalid user input":
            return jsonify({"error": "Invalid user input. No valid ingredients found."}), 400

        
        if response_text.startswith("```") and response_text.endswith("```"):
            response_text = response_text.split("\n", 1)[-1].rsplit("\n", 1)[0].strip()


        try:
            ingredient_list = json.loads(response_text)
        except json.JSONDecodeError:
            raise ValueError(f"Invalid JSON response from Gemini API: {response_text}")

        for item in ingredient_list:
            ingredient_name = item["ingredient"]
            unit = item["unit"]
            amount = float(item["amount"])




            # Custom conversion for eggs
            if ingredient_name.lower() in ["egg", "eggs"]:
                converted_value = amount * 50
                unit = "grams"
                converted_ingredients.append({
                    "ingredient": ingredient_name,
                    "converted_value": converted_value,
                    "unit": unit,
                    "source": "predefined"
                })
                continue


            elif ingredient_name.lower() in ["egg yolk"]:
                converted_value = amount * 18
                unit = "grams"
                converted_ingredients.append({
                    "ingredient": ingredient_name,
                    "converted_value": converted_value,
                    "unit": unit,
                    "source": "predefined"
                })
                continue


            elif ingredient_name.lower() in ["egg white"]:
                converted_value = amount * 30
                unit = "grams"
                converted_ingredients.append({
                    "ingredient": ingredient_name,
                    "converted_value": converted_value,
                    "unit": unit,
                    "source": "predefined"
                })
                continue


            else:
              ingredient_data = Ingredient.query.filter(
                  Ingredient.ingredient_name.ilike(ingredient_name)
              ).with_entities(
                  Ingredient.density_g_,
                  Ingredient.cup_g,
                  Ingredient.tbsp_g,
                  Ingredient.tsp_g
              ).first()

        
              if not ingredient_data:
                  ingredient_data = Ingredient.query.filter(
                      Ingredient.ingredient_name.ilike(f"%{ingredient_name}%")
                  ).with_entities(
                      Ingredient.density_g_,
                      Ingredient.cup_g,
                      Ingredient.tbsp_g,
                      Ingredient.tsp_g
                  ).first()


            if ingredient_data:
                conversion_factor = None

                if unit in ["cup", "cups"]:
                    conversion_factor = ingredient_data.cup_g
                elif unit in ["spoon", "spoons", "tbsp", "tablespoon", "spoonful", "spoonfuls", "tablespoons"]:
                    conversion_factor = ingredient_data.tbsp_g
                elif unit in ["tsp", "teaspoon", "teaspoons"]:
                    conversion_factor = ingredient_data.tsp_g
                elif unit in ["g", "grams", "gram"]:
                    conversion_factor = 1
                elif unit in ["fl oz", "fluid ounce", "fluid ounces"]:
                    conversion_factor = 29.5735 * ingredient_data.density_g_
                elif unit in ["mL", "ml", "milliliter", "milliliters"]:
                    conversion_factor = ingredient_data.density_g_
                elif unit in ["oz", "ounce", "ounces"]:
                    conversion_factor = 28.3495
                elif unit in ["lbs", "pound", "pounds"]:
                    conversion_factor = 453.592
                elif unit in["handful", "handfuls"]:
                    conversion_factor = 30
                elif unit in ["pinch", "pinches", "dash"]:
                    conversion_factor = 0.3
                elif unit in ["L", "liter", "liters"] and ingredient_data.density_g_ is not None:
                    conversion_factor = ingredient_data.density_g_ * 1000
                elif unit in ["gallon", "gallons"] and ingredient_data.density_g_ is not None:
                    conversion_factor = ingredient_data.density_g_ * 3785.41
                elif unit in ["clove", "cloves"]:
                    conversion_factor = 5

                if conversion_factor:
                    converted_value = amount * conversion_factor
                    converted_ingredients.append({
                        "ingredient": ingredient_name,
                        "converted_value": converted_value,
                        "unit": "grams",
                        "source": "database"
                    })
                else:
                    converted_ingredients.append({
                        "ingredient": ingredient_name,
                        "error": f"No conversion factor found for {unit}"
                    })

            # Gemini API Fallback if ingredient is missing from DB
            else:

                gemini_response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=f"Estimate the weight in grams for {amount} {unit} of {ingredient_name}. "
                             "Completely ignore any words that are names, places, or unknown terms, and do NOT attempt to estimate them."
                             "If the ingredient is a whole fruit or vegetable, assume average size. "
                             "Return only the estimated value as a number, no extra text."
                             "If unsure about an ingredient, or if the ingredient is unknown or unrecognized, dont estimate or return anything for that ingredient."

                )
                try:
                    fallback_value = float(gemini_response.text.strip())
                except ValueError:
                    fallback_value = None

                if fallback_value is not None and fallback_value > 0:
                    converted_ingredients.append({
                        "ingredient": ingredient_name,
                        "converted_value": fallback_value,
                        "unit": "grams",
                        "source": "gemini"
                    })
                else:
                    converted_ingredients.append({
                        "ingredient": ingredient_name,
                        "error": "Gemini API failed to estimate weight"
                    })

        formatted_recipe = "\n".join(
            [f"{item['converted_value']} {item['unit']} of {item['ingredient']}" for item in converted_ingredients if
             "converted_value" in item]
        )

        return jsonify({
            "formatted_recipe": formatted_recipe  # Send formatted string
        })


    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": f"Something went wrong: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=False)

