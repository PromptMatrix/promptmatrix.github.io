import requests

def check_dashboard():
    url = "http://127.0.0.1:8000/dashboard"
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print("Dashboard served successfully.")
            # Check for branding or specific elements
            if "PromptMatrix" in response.text:
                print("Branding 'PromptMatrix' found in HTML.")
            if "dashboard.js" in response.text:
                print("Reference to dashboard.js found.")
            if "glass" in response.text or "theme" in response.text:
                print("Modern CSS terms found in HTML.")
        else:
            print(f"Error: Received status code {response.status_code}")
    except Exception as e:
        print(f"Connection failed: {e}")

if __name__ == "__main__":
    check_dashboard()
