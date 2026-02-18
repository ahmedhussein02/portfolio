import os
import base64
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class AzureService:
    def __init__(self):
        self.doc_client = DocumentIntelligenceClient(
            os.getenv("DOC_INTEL_ENDPOINT"), 
            AzureKeyCredential(os.getenv("DOC_INTEL_KEY"))
        )
        
        self.search_client = SearchClient(
            os.getenv("AZURE_SEARCH_ENDPOINT"),
            os.getenv("AZURE_SEARCH_INDEX_NAME"),
            AzureKeyCredential(os.getenv("AZURE_SEARCH_KEY"))
        )

        self.ai_client = OpenAI(
            base_url="https://models.inference.ai.azure.com", 
            api_key=os.getenv("GITHUB_OPENAI_KEY")
        )

    def analyze_invoice(self, file):
        try:
            file_bytes = file.read()
            poller = self.doc_client.begin_analyze_document(
                model_id="prebuilt-invoice",
                body=AnalyzeDocumentRequest(bytes_source=file_bytes)
            )
            result = poller.result()

            invoice_data = {}

            if result.documents:
                fields = result.documents[0].fields
                
                # Use .content as the ultimate fallback for any field
                def extract(key):
                    field = fields.get(key)
                    if not field: return "Not found"
                    return field.value_string if hasattr(field, 'value_string') and field.value_string else field.content

                # --- FIX TAX IDs + IBAN EXTRACTION (Minimal Change) ---

                # Vendor Tax ID (sometimes missing depending on invoice format)
                vendor_tax = extract("VendorTaxId")

                # Client Tax ID (field often not provided by model)
                client_tax = extract("CustomerTaxId")

                # IBAN extraction (PaymentDetails is an array, wildcard does NOT work)
                iban_value = "Not found"
                payment_details = fields.get("PaymentDetails")

                if payment_details and payment_details.value_array:
                    first_payment = payment_details.value_array[0].value_object
                    iban_field = first_payment.get("IBAN")
                    if iban_field:
                        iban_value = iban_field.value_string or iban_field.content

                invoice_data = {
                    "InvoiceNo": extract("InvoiceId"),
                    "VendorName": extract("VendorName"),
                    "VendorAddress": extract("VendorAddress"),
                    "VendorTaxId": vendor_tax,
                    "ClientName": extract("CustomerName"),
                    "ClientAddress": extract("CustomerAddress"),
                    "ClientTaxId": client_tax,
                    "IBAN": iban_value,
                    "InvoiceDate": str(fields.get("InvoiceDate").value_date) if fields.get("InvoiceDate") else "N/A",
                    "InvoiceTotal": extract("InvoiceTotal")
                }

                
                # Simple count for items
                items = fields.get("Items")
                invoice_data["TotalItems"] = len(items.value_array) if items else 0

            return invoice_data

        except Exception as e:
            print(f"Azure Error: {e}")
            return {"error": str(e)}

    def get_rag_response(self, user_query):
        """The New Smart Chat Logic"""
        try:
            # A. Convert user question to vector
            query_vector = self.ai_client.embeddings.create(
                input=[user_query], 
                model="text-embedding-3-small"
            ).data[0].embedding

            # B. Search using Vector + Text (Hybrid Search)
            vector_query = VectorizedQuery(vector=query_vector, k_nearest_neighbors=3, fields="content_vector")
            
            results = self.search_client.search(
                search_text=user_query,
                vector_queries=[vector_query],
                select=["content", "source"],
                top=3
            )

            context = "\n".join([f"Source [{r['source']}]: {r['content']}" for r in results])

            if not context:
                return "I couldn't find any information in the ERP system to answer that."

            # C. Generate answer with GPT-4o
            response = self.ai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are an ERP Assistant. Use the provided context to answer. Be concise. If the info is missing, say so."},
                    {"role": "user", "content": f"Context:\n{context}\n\nQuestion: {user_query}"}
                ]
            )

            return response.choices[0].message.content
        except Exception as e:
            print(f"RAG Error: {e}")
            return "Sorry, I encountered an error while searching the knowledge base."