import os
import google.generativeai as genai
from dotenv import load_dotenv

def main():
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY")
    genai.configure(api_key=key)
    
    models_to_test = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-3.5-flash",
        "gemini-flash-latest",
        "gemini-pro-latest"
    ]
    
    for model_name in models_to_test:
        print(f"\n--- Testing {model_name} ---")
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content("Hi")
            print(f"Success! Response: {response.text}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
