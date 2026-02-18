from flask import Flask, render_template, request, jsonify
from services.azure_service import AzureService

app = Flask(__name__)
azure = AzureService()

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/certifications')
def certifications():
    return render_template('certifications.html')

@app.route('/erp-lab')
def erp_lab():
    return render_template('erp_demo.html', title="AI ERP Lab")

@app.route('/api/upload-invoice', methods=['POST'])
def upload_invoice():
    file = request.files.get('file')
    if not file: return jsonify({"error": "No file"}), 400
    return jsonify(azure.analyze_invoice(file))

@app.route('/api/chat', methods=['POST'])
def chat():
    query = request.json.get('query')
    return jsonify({"response": azure.get_rag_response(query)})

if __name__ == '__main__':
    app.run(debug=True)