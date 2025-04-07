# Webpage to Alai Presentation Converter

A Python tool that scrapes web pages and automatically converts them into professional presentations using the Alai API.

## Features

- Web page scraping using FirecrawlApp
- Extraction of titles, paragraphs, and images from web content
- Automatic creation of structured presentations with Alai
- Authentication management for Alai API
- Image processing and uploading for slide content

## Requirements

- Python 3.6+
- Firecrawl API key
- Alai account credentials

## Setup

1. Clone this repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Create a `.env` file with the following variables:
   ```
   FIRECRAWL_API_KEY="your_firecrawl_api_key"
   ALAI_API_KEY="your_alai_api_key"
   ALAI_EMAIL="your_alai_email"
   ALAI_PASSWORD="your_alai_password"
   ```

## Usage

Run the script with a URL to convert:

```
python webpage_to_alai.py https://example.com/article
```

The script will:
1. Scrape the provided URL
2. Extract structured content
3. Create a new presentation in your Alai account
4. Generate slides with appropriate content and images
5. Provide a link to the completed presentation

## Data

The script saves extracted data to `data.json` for debugging or further processing.
