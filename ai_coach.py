from dotenv import load_dotenv
import os

load_dotenv()  # loads variables from .env file into environment

access_key = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
access_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
dashscope_key = os.getenv("DASHSCOPE_API_KEY")

print(access_key, access_secret, dashscope_key)  # just to test if loaded properly

import os
import json
import uuid
import datetime
from flask import Flask, request, jsonify, render_template, redirect, url_for
import pandas as pd
from alibabacloud_ocr_api20210707.client import Client as OcrClient
from alibabacloud_tea_openapi import models as open_api_models
from alibabacloud_ocr_api20210707 import models as ocr_models
import dashscope
from dashscope.aigc.generation import Generation

app = Flask(__name__)

# Mock database for storing receipts and expenses
RECEIPTS_DB = []
EXPENSES_DB = []

# Configure Alibaba Cloud credentials
def create_ocr_client():
    """Create and return an Alibaba Cloud OCR client"""
    config = open_api_models.Config(
        access_key_id=os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_ID'),
        access_key_secret=os.environ.get('ALIBABA_CLOUD_ACCESS_KEY_SECRET')
    )
    config.endpoint = 'ocr-api.cn-hangzhou.aliyuncs.com'
    return OcrClient(config)

# Configure DashScope
dashscope.api_key = os.environ.get('DASHSCOPE_API_KEY')

# Categories for expenses
CATEGORIES = [
    "Groceries", "Dining", "Transportation", "Entertainment", 
    "Shopping", "Utilities", "Healthcare", "Travel", "Other"
]

@app.route('/')
def index():
    """Render the main application page"""
    return render_template('index.html', categories=CATEGORIES)

@app.route('/upload', methods=['POST'])
def upload_receipt():
    """Handle receipt upload and OCR processing"""
    if 'receipt' not in request.files:
        return jsonify({"error": "No receipt file uploaded"}), 400
    
    receipt_file = request.files['receipt']
    if receipt_file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    
    # Save the uploaded file temporarily
    temp_path = f"/tmp/{uuid.uuid4()}.jpg"
    receipt_file.save(temp_path)
    
    try:
        # Process the receipt with OCR
        extracted_data = process_receipt_with_ocr(temp_path)
        
        # Create receipt and expense records
        receipt_id = str(uuid.uuid4())
        receipt_data = {
            "id": receipt_id,
            "date": extracted_data.get("date", datetime.datetime.now().strftime("%Y-%m-%d")),
            "merchant": extracted_data.get("merchant", "Unknown"),
            "total_amount": extracted_data.get("total_amount", 0.0),
            "items": extracted_data.get("items", []),
            "raw_text": extracted_data.get("raw_text", "")
        }
        
        # Auto-categorize the expense
        category = categorize_expense(receipt_data)
        
        # Create expense record
        expense = {
            "id": str(uuid.uuid4()),
            "receipt_id": receipt_id,
            "date": receipt_data["date"],
            "merchant": receipt_data["merchant"],
            "amount": receipt_data["total_amount"],
            "category": category
        }
        
        # Save to our mock database
        RECEIPTS_DB.append(receipt_data)
        EXPENSES_DB.append(expense)
        
        # Clean up
        os.remove(temp_path)
        
        return jsonify({
            "status": "success",
            "receipt": receipt_data,
            "expense": expense
        })
        
    except Exception as e:
        # Clean up on error
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"error": str(e)}), 500

def process_receipt_with_ocr(image_path):
    """Process a receipt image with Alibaba Cloud OCR"""
    client = create_ocr_client()
    
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    request = ocr_models.RecognizeReceiptRequest(
        body=image_bytes
    )
    
    try:
        response = client.recognize_receipt(request)
        result = response.body.to_map()
        
        # Parse OCR results
        raw_text = result.get('Data', {}).get('Content', '')
        
        # Extract structured data from the OCR text
        extracted = extract_receipt_data(raw_text)
        extracted['raw_text'] = raw_text
        
        return extracted
    except Exception as e:
        print(f"OCR processing error: {e}")
        raise

def extract_receipt_data(ocr_text):
    """Extract structured data from OCR text"""
    # Basic parsing logic - in a real application you would need more robust parsing
    lines = ocr_text.split('\n')
    
    # Default values
    data = {
        "merchant": "Unknown",
        "date": datetime.datetime.now().strftime("%Y-%m-%d"),
        "total_amount": 0.0,
        "items": []
    }
    
    # Simple parsing - this would need to be much more sophisticated in a real app
    for line in lines:
        if "total" in line.lower():
            # Try to extract total amount
            parts = line.split()
            for part in parts:
                try:
                    if part.startswith("$"):
                        data["total_amount"] = float(part.replace("$", "").replace(",", ""))
                    else:
                        amount = float(part.replace(",", ""))
                        data["total_amount"] = amount
                        break
                except ValueError:
                    continue
        
        # Very basic merchant detection - first line that's not a date
        if data["merchant"] == "Unknown" and not any(x in line.lower() for x in ["date", "receipt", "invoice"]):
            data["merchant"] = line.strip()
        
        # Simple date detection
        date_formats = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d/%m/%Y"]
        for fmt in date_formats:
            try:
                datetime.datetime.strptime(line.strip(), fmt)
                data["date"] = line.strip()
                break
            except ValueError:
                continue
    
    # Extract items (very simplified)
    item_section = False
    for line in lines:
        if "item" in line.lower() or "qty" in line.lower():
            item_section = True
            continue
        
        if item_section and "total" not in line.lower() and len(line.strip()) > 0:
            # Simplified item extraction
            data["items"].append({"description": line.strip(), "price": 0.0})
    
    return data

def categorize_expense(receipt_data):
    """Automatically categorize an expense based on the receipt data"""
    # Use DashScope to categorize the expense
    prompt = f"""
    I have a receipt from {receipt_data['merchant']} for ${receipt_data['total_amount']}.
    The raw text from the receipt is: {receipt_data.get('raw_text', '')}
    
    Please categorize this expense into exactly one of these categories:
    {', '.join(CATEGORIES)}
    
    Return only the category name.
    """
    
    try:
        response = Generation.call(
            model='qwen-max',
            prompt=prompt,
            top_p=0.8,
            result_format='text'
        )
        
        if response.status_code == 200:
            # Extract the category from the response
            predicted_category = response.output.text.strip()
            
            # Ensure it's a valid category
            if predicted_category in CATEGORIES:
                return predicted_category
            else:
                # Find the closest match or default to "Other"
                for category in CATEGORIES:
                    if category.lower() in predicted_category.lower():
                        return category
                return "Other"
        else:
            print(f"DashScope error: {response.code}, {response.message}")
            return "Other"
    except Exception as e:
        print(f"Categorization error: {e}")
        return "Other"

@app.route('/expenses')
def get_expenses():
    """Return all expenses"""
    return jsonify(EXPENSES_DB)

@app.route('/ask', methods=['POST'])
def ask_question():
    """Process natural language questions about expenses"""
    data = request.json
    if not data or 'question' not in data:
        return jsonify({"error": "No question provided"}), 400
    
    question = data['question']
    
    # Convert expenses to DataFrame for analysis
    expenses_df = pd.DataFrame(EXPENSES_DB)
    
    # Get insights using DashScope
    insights = get_insights_from_dashscope(question, expenses_df)
    
    return jsonify({"answer": insights})

def get_insights_from_dashscope(question, expenses_df):
    """Get spending insights using DashScope"""
    # Prepare expense summary for the prompt
    if expenses_df.empty:
        expenses_summary = "No expenses recorded yet."
    else:
        total_spent = expenses_df['amount'].sum()
        by_category = expenses_df.groupby('category')['amount'].sum().to_dict()
        
        expenses_summary = f"Total spent: ${total_spent:.2f}\n"
        expenses_summary += "Spending by category:\n"
        for category, amount in by_category.items():
            expenses_summary += f"- {category}: ${amount:.2f}\n"
        
        if 'date' in expenses_df.columns:
            # Get recent expenses
            expenses_df['date'] = pd.to_datetime(expenses_df['date'])
            recent_expenses = expenses_df.sort_values('date', ascending=False).head(5)
            
            expenses_summary += "\nRecent expenses:\n"
            for _, row in recent_expenses.iterrows():
                expenses_summary += f"- {row['date'].strftime('%Y-%m-%d')}: ${row['amount']:.2f} at {row['merchant']} ({row['category']})\n"
    
    # Create prompt for DashScope
    prompt = f"""
    You are an AI Spending Coach helping a user understand their expenses.
    
    Here is a summary of the user's expenses:
    {expenses_summary}
    
    The user's question is: "{question}"
    
    Provide a helpful, concise analysis addressing their question based on the expense data.
    Focus on actionable insights and useful observations about spending patterns.
    """
    
    try:
        response = Generation.call(
            model='qwen-max',
            prompt=prompt,
            top_p=0.8,
            result_format='text'
        )
        
        if response.status_code == 200:
            return response.output.text
        else:
            return f"Sorry, I couldn't analyze your expenses. Error: {response.message}"
    except Exception as e:
        print(f"DashScope error: {e}")
        return "Sorry, I couldn't analyze your expenses due to a technical issue."

@app.route('/templates/index.html')
def get_template():
    """Return the HTML template for the UI"""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>AI Spending Coach</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {
                font-family: Arial, sans-serif;
                margin: 0;
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                max-width: 800px;
                margin: 0 auto;
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            }
            h1 {
                color: #333;
                text-align: center;
            }
            .tab {
                overflow: hidden;
                border: 1px solid #ccc;
                background-color: #f1f1f1;
                border-radius: 4px 4px 0 0;
            }
            .tab button {
                background-color: inherit;
                float: left;
                border: none;
                outline: none;
                cursor: pointer;
                padding: 14px 16px;
                transition: 0.3s;
            }
            .tab button:hover {
                background-color: #ddd;
            }
            .tab button.active {
                background-color: #4CAF50;
                color: white;
            }
            .tabcontent {
                display: none;
                padding: 20px;
                border: 1px solid #ccc;
                border-top: none;
                border-radius: 0 0 4px 4px;
            }
            input[type="file"],
            input[type="text"],
            button {
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
            }
            input[type="text"] {
                width: 100%;
                box-sizing: border-box;
            }
            button {
                background-color: #4CAF50;
                color: white;
                border: none;
                cursor: pointer;
            }
            button:hover {
                background-color: #45a049;
            }
            .expense-card {
                border: 1px solid #ddd;
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
            }
            .loading {
                text-align: center;
                margin: 20px 0;
            }
            .chat-box {
                height: 300px;
                overflow-y: auto;
                border: 1px solid #ddd;
                padding: 10px;
                margin: 10px 0;
                border-radius: 4px;
            }
            .message {
                margin: 10px 0;
                padding: 10px;
                border-radius: 4px;
            }
            .user-message {
                background-color: #e1f5fe;
                margin-left: 20%;
                margin-right: 0;
            }
            .ai-message {
                background-color: #f1f1f1;
                margin-right: 20%;
                margin-left: 0;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>AI Spending Coach</h1>
            
            <div class="tab">
                <button class="tablinks active" onclick="openTab(event, 'Upload')">Upload Receipt</button>
                <button class="tablinks" onclick="openTab(event, 'Expenses')">View Expenses</button>
                <button class="tablinks" onclick="openTab(event, 'Ask')">Ask Coach</button>
            </div>
            
            <div id="Upload" class="tabcontent" style="display: block;">
                <h2>Upload Receipt</h2>
                <form id="receipt-form" enctype="multipart/form-data">
                    <input type="file" id="receipt" name="receipt" accept="image/*" required>
                    <button type="submit">Process Receipt</button>
                </form>
                <div id="upload-result"></div>
                <div id="loading" class="loading" style="display: none;">Processing receipt...</div>
            </div>
            
            <div id="Expenses" class="tabcontent">
                <h2>Your Expenses</h2>
                <div id="expenses-list">Loading expenses...</div>
            </div>
            
            <div id="Ask" class="tabcontent">
                <h2>Ask Your Spending Coach</h2>
                <div class="chat-box" id="chat-box"></div>
                <div>
                    <input type="text" id="question" placeholder="Ask about your spending...">
                    <button onclick="askQuestion()">Ask</button>
                </div>
            </div>
        </div>
        
        <script>
            // Open tab function
            function openTab(evt, tabName) {
                var i, tabcontent, tablinks;
                tabcontent = document.getElementsByClassName("tabcontent");
                for (i = 0; i < tabcontent.length; i++) {
                    tabcontent[i].style.display = "none";
                }
                tablinks = document.getElementsByClassName("tablinks");
                for (i = 0; i < tablinks.length; i++) {
                    tablinks[i].className = tablinks[i].className.replace(" active", "");
                }
                document.getElementById(tabName).style.display = "block";
                evt.currentTarget.className += " active";
                
                if (tabName === "Expenses") {
                    loadExpenses();
                }
            }
            
            // Handle receipt form submission
            document.getElementById("receipt-form").addEventListener("submit", function(e) {
                e.preventDefault();
                const formData = new FormData();
                const fileField = document.getElementById("receipt");
                
                if (fileField.files[0]) {
                    formData.append("receipt", fileField.files[0]);
                    
                    // Show loading indicator
                    document.getElementById("loading").style.display = "block";
                    document.getElementById("upload-result").innerHTML = "";
                    
                    fetch("/upload", {
                        method: "POST",
                        body: formData
                    })
                    .then(response => response.json())
                    .then(data => {
                        document.getElementById("loading").style.display = "none";
                        if (data.error) {
                            document.getElementById("upload-result").innerHTML = 
                                `<p style="color: red;">Error: ${data.error}</p>`;
                        } else {
                            document.getElementById("upload-result").innerHTML = 
                                `<div class="expense-card">
                                    <h3>Receipt Processed</h3>
                                    <p>Merchant: ${data.receipt.merchant}</p>
                                    <p>Date: ${data.receipt.date}</p>
                                    <p>Amount: $${data.receipt.total_amount}</p>
                                    <p>Category: ${data.expense.category}</p>
                                </div>`;
                        }
                    })
                    .catch(error => {
                        document.getElementById("loading").style.display = "none";
                        document.getElementById("upload-result").innerHTML = 
                            `<p style="color: red;">Error: ${error.message}</p>`;
                    });
                }
            });
            
            // Load expenses
            function loadExpenses() {
                document.getElementById("expenses-list").innerHTML = "Loading...";
                
                fetch("/expenses")
                    .then(response => response.json())
                    .then(expenses => {
                        if (expenses.length === 0) {
                            document.getElementById("expenses-list").innerHTML = 
                                "<p>No expenses yet. Upload some receipts!</p>";
                            return;
                        }
                        
                        let html = "";
                        expenses.forEach(expense => {
                            html += `
                                <div class="expense-card">
                                    <h3>${expense.merchant}</h3>
                                    <p>Date: ${expense.date}</p>
                                    <p>Amount: $${expense.amount}</p>
                                    <p>Category: ${expense.category}</p>
                                </div>
                            `;
                        });
                        
                        document.getElementById("expenses-list").innerHTML = html;
                    })
                    .catch(error => {
                        document.getElementById("expenses-list").innerHTML = 
                            `<p style="color: red;">Error loading expenses: ${error.message}</p>`;
                    });
            }
            
            // Ask a question function
            function askQuestion() {
                const question = document.getElementById("question").value.trim();
                if (!question) return;
                
                // Add user message to chat
                const chatBox = document.getElementById("chat-box");
                const userMessage = document.createElement("div");
                userMessage.className = "message user-message";
                userMessage.textContent = question;
                chatBox.appendChild(userMessage);
                
                // Clear input
                document.getElementById("question").value = "";
                
                // Add loading message
                const loadingMessage = document.createElement("div");
                loadingMessage.className = "message ai-message";
                loadingMessage.textContent = "Thinking...";
                chatBox.appendChild(loadingMessage);
                
                // Scroll to bottom
                chatBox.scrollTop = chatBox.scrollHeight;
                
                // Send question to API
                fetch("/ask", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({ question: question })
                })
                .then(response => response.json())
                .then(data => {
                    // Remove loading message
                    chatBox.removeChild(loadingMessage);
                    
                    // Add AI response
                    const aiMessage = document.createElement("div");
                    aiMessage.className = "message ai-message";
                    aiMessage.textContent = data.answer;
                    chatBox.appendChild(aiMessage);
                    
                    // Scroll to bottom
                    chatBox.scrollTop = chatBox.scrollHeight;
                })
                .catch(error => {
                    // Remove loading message
                    chatBox.removeChild(loadingMessage);
                    
                    // Add error message
                    const errorMessage = document.createElement("div");
                    errorMessage.className = "message ai-message";
                    errorMessage.textContent = "Sorry, I encountered an error: " + error.message;
                    chatBox.appendChild(errorMessage);
                    
                    // Scroll to bottom
                    chatBox.scrollTop = chatBox.scrollHeight;
                });
            }
            
            // Add event listener for pressing Enter in the question input
            document.getElementById("question").addEventListener("keypress", function(event) {
                if (event.key === "Enter") {
                    askQuestion();
                }
            });
        </script>
    </body>
    </html>
    """

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))