# B&E Financial - AI-Powered Personal Finance Assistant
B&E Financial is a personal finance web application designed to help users manage their expenses efficiently. With intelligent receipt scanning, automatic expense categorization, and an integrated AI chatbot, SmartFinance empowers users to take control of their financial life.

# Prototype
https://www.figma.com/design/EuL0P9YMdtYkuyZSdK1E6x/Figma-UI-kit---Money-Management-Mobile-App--Community---Community-?node-id=301-73213&t=8BLPkG55QWJJcBPp-1

## Features
-  **Upload Receipts** — Scan paper receipts using Alibaba Cloud OCR
-  **AI Categorization** — Automatically categorize expenses using DashScope (Qwen)
-  **AI Chatbot** — Get personalized financial advice and spending insights
-  **Spending Dashboard** — Visualize where your money goes each day/week/month
-  
##  Tech Stack

- **Frontend**: HTML
- **Backend**: Flask (Python)
- **OCR**: Alibaba Cloud OCR API
- **AI**: DashScope (Qwen model)

##  How It Works

1. **Upload** a receipt image.
2. **OCR** extracts text from the receipt using Alibaba Cloud OCR.
3. Extracted data is sent to **DashScope AI** to categorize the expenses.
4. The app displays categorized spending in a table and a visual dashboard.
5. Use the **AI Chatbot** to ask for tips, spending summaries, and financial coaching.
