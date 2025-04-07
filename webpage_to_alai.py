import os
import sys
import time
import json
import uuid
import requests
import websocket
from io import BytesIO
from functools import partial
from dotenv import load_dotenv
from pydantic import BaseModel
from firecrawl import FirecrawlApp

# Load environment variables
load_dotenv()


def extract_webpage_data(url):
    """
    Scrape the given URL using FirecrawlApp and extract a JSON with keys:
    `title`, `paragraphs`, and `images`.
    """
    app = FirecrawlApp(api_key=os.getenv("FIRECRAWL_API_KEY"))

    class ExtractionSchema(BaseModel):
        title: str
        images: dict
        paragraphs: dict

    extracted_result = None

    # Continue extracting until all conditions are met
    while not (
        extracted_result
        and "title" in extracted_result["data"]
        and "images" in extracted_result["data"]
        and "paragraphs" in extracted_result["data"]
        and extracted_result["data"]["title"] != ""
        and len(extracted_result["data"]["paragraphs"]) > 2
    ):
        print("Extracting data...")
        extracted_result = app.extract(
            [url],
            {
                "prompt": """
You'll be given the raw HTML of a webpage. Parse it and return a single JSON object with three keys: `title`, `paragraphs`, and `images`.

1. **Extract the page title**
    - Grab the text inside `<title>` and set `"title"` to that string.

2. **Build the `paragraphs` dictionary**
    - Keys: section headings.
    - Values: the concatenated plain text relevant paragraphs under that heading.
    - Always include an `"Introduction"` key first.
    - Include at least 4–6 sections total.
    - Order the entries exactly as they appear in the HTML.

3. **Build the `images` dictionary**
    - Keys: must exactly match the keys in `paragraphs`.
    - Values: a list of absolute, publicly accessible URLs from all `<img src="…">` tags within that section.
    - Try to include at least one image URL per section but if a section has no images, use an empty list. DO NOT INCLUDE EMPTY STRINGS IN THE LISTS.
    - Try to include mostly png images.
    - Include as many png images as possible.

4. **Output format**
    ```json
    {
        "title": "…",
        "paragraphs": {
            "Introduction": "…",
            "Section 1 Heading": "…",
            …
        },
        "images": {
            "Introduction": ["https://…", …],
            "Section 1 Heading": [ … ],
            …
        }
    }
                """,
                "schema": ExtractionSchema.model_json_schema(),
            },
        )
        # Save the output for debugging or further processing.
        with open("data.json", "w") as outfile:
            json.dump(extracted_result["data"], outfile, indent=4)

    return extracted_result["data"]


class AuthManager:
    """
    Manages Alai authentication tokens.
    """

    def __init__(self):
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = 0
        self.email = os.getenv("ALAI_EMAIL")
        self.password = os.getenv("ALAI_PASSWORD")
        self.api_key = os.getenv("ALAI_API_KEY")

    def get_valid_token(self):
        current_time = int(time.time())
        if self.access_token and self.token_expiry > current_time + 300:
            return self.access_token

        if self.refresh_token:
            try:
                return self.refresh_access_token()
            except Exception as err:
                print(f"Refresh failed: {err}. Falling back to password auth.")

        if not self.email or not self.password:
            raise ValueError("Missing ALAI_EMAIL or ALAI_PASSWORD in environment variables")

        auth_url = "https://api.getalai.com/auth/v1/token?grant_type=password"
        headers = {
            "accept": "*/*",
            "accept-language": "en",
            "apikey": self.api_key,
            "authorization": "Bearer " + self.api_key,
            "content-type": "application/json;charset=UTF-8",
            "x-client-info": "supabase-js-web/2.45.4",
            "x-supabase-api-version": "2024-01-01",
        }
        payload = {"email": self.email, "password": self.password}

        response = requests.post(auth_url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"Authentication error: {response.status_code}, {response.text}")

        data = response.json()
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        self.token_expiry = int(time.time()) + data.get("expires_in", 3600)
        return self.access_token

    def refresh_access_token(self):
        if not self.refresh_token:
            raise ValueError("No refresh token available")

        auth_url = "https://api.getalai.com/auth/v1/token?grant_type=refresh_token"
        headers = {
            "accept": "*/*",
            "accept-language": "en",
            "apikey": self.api_key,
            "authorization": "Bearer " + self.api_key,
            "content-type": "application/json;charset=UTF-8",
            "x-client-info": "supabase-js-web/2.45.4",
            "x-supabase-api-version": "2024-01-01",
        }
        payload = {"refresh_token": self.refresh_token}

        response = requests.post(auth_url, headers=headers, json=payload)
        if response.status_code != 200:
            self.refresh_token = None
            raise Exception(f"Refresh token error: {response.status_code}, {response.text}")

        data = response.json()
        self.access_token = data.get("access_token")
        self.refresh_token = data.get("refresh_token")
        self.token_expiry = int(time.time()) + data.get("expires_in", 3600)
        return self.access_token

    def ensure_token(self, token):
        current_time = int(time.time())
        if self.token_expiry <= current_time + 300:
            return self.get_valid_token()
        return token


class PresentationClient:
    """
    Provides methods for interacting with the Alai presentation API.
    """

    def __init__(self, auth_manager):
        self.auth_manager = auth_manager

    def create_presentation(self, title):
        token = self.auth_manager.get_valid_token()
        presentation_uuid = str(uuid.uuid4())
        url = "https://alai-standalone-backend.getalai.com/create-new-presentation"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": "https://app.getalai.com",
        }
        payload = {
            "presentation_id": presentation_uuid,
            "presentation_title": title,
            "create_first_slide": True,
            "theme_id": "a6bff6e5-3afc-4336-830b-fbc710081012",
            "default_color_set_id": 0,
        }
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"Error creating presentation: {response.status_code}, {response.text}")
        return response.json()

    def pick_variant(self, slide_id, variant_id):
        token = self.auth_manager.get_valid_token()
        url = "https://alai-standalone-backend.getalai.com/pick-slide-variant"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": "https://app.getalai.com",
        }
        payload = {"slide_id": slide_id, "variant_id": variant_id}
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            print(f"Warning: Picking variant failed: {response.status_code}, {response.text}")
            return None
        print(f"Variant {variant_id} successfully applied to slide {slide_id}")
        return response.json()

    def create_slide(self, presentation_id, slide_order=1, color_set_id=0):
        token = self.auth_manager.get_valid_token()
        slide_uuid = str(uuid.uuid4())
        url = "https://alai-standalone-backend.getalai.com/create-new-slide"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": "https://app.getalai.com",
        }
        payload = {
            "slide_id": slide_uuid,
            "presentation_id": presentation_id,
            "product_type": "PRESENTATION_CREATOR",
            "slide_order": slide_order,
            "color_set_id": color_set_id,
        }
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise Exception(f"Error creating slide: {response.status_code}, {response.text}")
        return slide_uuid

    def remove_slide(self, slide_id):
        token = self.auth_manager.get_valid_token()
        url = "https://alai-standalone-backend.getalai.com/delete-slides"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en",
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Origin": "https://app.getalai.com",
        }
        payload = [slide_id]
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code == 200:
            print(f"Slide {slide_id} deleted successfully.")

    def generate_share_link(self, presentation_id):
        token = self.auth_manager.get_valid_token()
        url = "https://alai-standalone-backend.getalai.com/upsert-presentation-share"
        headers = {
            "Accept": "*/*",
            "Accept-Language": "en",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Origin": "https://app.getalai.com",
        }
        response = requests.post(url, headers=headers, json={"presentation_id": presentation_id})
        share_id = response.text.strip('"')
        return f"https://app.getalai.com/view/{share_id}"


def process_images_for_slide(token, presentation_id, image_urls):
    """
    Download and upload images for slide generation.
    """
    if not image_urls:
        return []

    upload_url = "https://alai-standalone-backend.getalai.com/upload-images-for-slide-generation"
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en",
        "Authorization": f"Bearer {token}",
        "Origin": "https://app.getalai.com",
    }
    files_list = []

    for idx, url in enumerate(image_urls):
        if not url.startswith("http"):
            continue
        img_response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36"
            },
        )
        if img_response.status_code != 200:
            print(f"Warning: Failed to download image: {img_response.status_code}\n{img_response.text}")
            continue

        img_data = BytesIO(img_response.content)
        content_type = img_response.headers.get("Content-Type", "image/jpeg").lower()
        extension = content_type.split("/")[-1]
        if extension in ["jpeg", "png", "gif", "webp"]:
            files_list.append(("files", (f"img{idx}.{extension}", img_data, content_type)))

    if not files_list:
        return []

    files_list.append(("upload_input", (None, json.dumps({"presentation_id": presentation_id}), "application/json")))
    upload_resp = requests.post(upload_url, headers=headers, files=files_list)
    upload_result = upload_resp.json()
    return upload_result.get("images", [])


def handle_slide_websocket(token, presentation_id, slide_id, slide_context, slide_images):
    """
    Establish a WebSocket connection to process a slide and select a variant.
    """
    websocket.enableTrace(False)
    ws_endpoint = "wss://alai-standalone-backend.getalai.com/ws/create-and-stream-slide-variants"
    ws_headers = [
        "Origin: https://app.getalai.com",
        "Cache-Control: no-cache",
        "Accept-Language: en",
        "Pragma: no-cache",
        "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
        "Sec-WebSocket-Version: 13",
        "Sec-WebSocket-Extensions: permessage-deflate; client_max_window_bits",
    ]

    received_msgs = []

    def ws_on_message(ws, msg):
        received_msgs.append(msg)

    def ws_on_error(ws, err):
        print("WebSocket error:", err)

    def ws_on_close(ws, code, msg):
        print("WebSocket closed:", code, msg)

    def ws_on_open(ws):
        payload = {
            "auth_token": token,
            "presentation_id": presentation_id,
            "slide_id": slide_id,
            "slide_specific_context": slide_context,
            "images_on_slide": slide_images,
            "additional_instructions": """
Make slides that are engaging and informative with minimal text. Follow these rules for every slide:

Title
– One short relevant title.

Content
– 3–5 bullet points, each ≤ 8 words.
– One idea per bullet.

Layout depends on image availability in images_on_slide:
– If With image: two‑column with text on left and image on right or vice-versa.
– If Without image: centered title + bullets.

If images_on_slide is empty, only then fallback to using text-only layout.
            """,
            "layout_type": "AI_GENERATED_LAYOUT",
            "update_tone_verbosity_calibration_status": False,
        }
        ws.send(json.dumps(payload))

    ws_app = websocket.WebSocketApp(
        ws_endpoint,
        header=ws_headers,
        on_open=ws_on_open,
        on_message=ws_on_message,
        on_error=ws_on_error,
        on_close=ws_on_close,
    )
    ws_app.run_forever()

    if len(received_msgs) < 2:
        print("Error: Insufficient messages received from WebSocket.")
        ws_app.close()
        if "Input should be 'image/jpeg', 'image/png', 'image/gif' or 'image/webp'" in received_msgs[-1]:
            return "Image Error"
        return False

    variant_info = json.loads(received_msgs[1])
    ws_app.close()
    return variant_info.get("id")


def assemble_slides(auth_manager, presentation_data, scraped_content):
    """
    Create and process slides using the scraped content.
    """
    client = PresentationClient(auth_manager)
    presentation_id = presentation_data.get("id")
    paragraphs = scraped_content["paragraphs"]
    section_keys = list(paragraphs.keys())
    images_dict = scraped_content["images"]
    current_slide_id = presentation_data["slides"][0]["id"]
    order_counter = 0

    for _ in range(len(section_keys)):
        # Choose section key, preferring "Introduction" if present
        current_key = "Introduction" if "Introduction" in paragraphs else section_keys[0]
        slide_context = f"{current_key}: {paragraphs[current_key]}"
        slide_images = process_images_for_slide(
            auth_manager.get_valid_token(), presentation_id, images_dict.get(current_key, [])
        )
        section_keys.remove(current_key)
        del paragraphs[current_key]

        attempt = 0
        while attempt < 4:
            if not current_slide_id:
                order_counter += 1
                current_slide_id = client.create_slide(presentation_id, slide_order=order_counter)
            print(f"Slide created with ID: {current_slide_id}")
            variant_id = handle_slide_websocket(
                auth_manager.get_valid_token(), presentation_id, current_slide_id, slide_context, slide_images
            )
            if variant_id and variant_id != "Image Error":
                client.pick_variant(current_slide_id, variant_id)
                current_slide_id = None
                break
            if variant_id == "Image Error" and attempt == 2:
                print("Image error encountered; proceeding without images.")
                slide_images = []
            client.remove_slide(current_slide_id)
            order_counter -= 1
            attempt += 1
            current_slide_id = None


def build_presentation(scraped_data, auth_manager):
    """
    Create an Alai presentation from scraped webpage data.
    """
    client = PresentationClient(auth_manager)
    title = scraped_data["title"]
    pres_data = client.create_presentation(title)
    pres_id = pres_data.get("id")
    print(f"Presentation created with ID: {pres_id}")
    assemble_slides(auth_manager, pres_data, scraped_data)
    share_link = client.generate_share_link(pres_id)
    return share_link


def main():
    """
    Main function to scrape a webpage and optionally create a presentation.
    """
    url = sys.argv[1] if len(sys.argv) > 1 else "https://en.wikipedia.org/wiki/Hello"
    if len(sys.argv) <= 1:
        print(f"No URL provided. Defaulting to: {url}")

    try:
        print(f"Scraping URL: {url}")
        scraped_content = extract_webpage_data(url)
        num_paragraphs = len(scraped_content["paragraphs"])
        total_images = sum(len(img_list) for img_list in scraped_content["images"].values())
        print(f"Extracted {num_paragraphs} paragraphs and {total_images} images.")
        print(f"Page title: {scraped_content['title']}")

        auth_mgr = AuthManager()
        #token = auth_mgr.get_valid_token()
        print("Authenticated with Alai.")
        shareable_link = build_presentation(scraped_content, auth_mgr)
        print("\nPresentation created successfully!")
        print(f"Shareable link: {shareable_link}\n")

    except Exception as err:
        print(f"Error occurred: {err}")


if __name__ == "__main__":
    main()
