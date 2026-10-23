# TripWise - AI Travel Planning with AWS Bedrock

**AWS Hackathon 2026 Submission**

## What It Does
Smart travel planning that respects your budget. Powered by AWS Bedrock (Amazon Nova Lite) for intelligent trip optimization, real-time price scraping, and conversational planning.

## AWS Services Used
- **AWS Bedrock**: AI-powered travel copilot
- **Amazon Nova Lite**: Natural language understanding & activity suggestions
- **Boto3 SDK**: Complete AWS integration

## Key Features
✅ Real-time flight, bus, train & hotel price scraping  
✅ AI-powered budget allocation & optimization  
✅ AWS Bedrock conversational copilot  
✅ Constraint-aware activity recommendations  
✅ Intelligent fallback system  

## Tech Stack
- **Backend**: FastAPI (Python) + AWS Bedrock + Boto3
- **Frontend**: React 19 + TypeScript + Vite
- **AI**: AWS Bedrock Amazon Nova Lite model
- **Scraping**: Selenium for real-time prices

## Quick Start
```bash
# Backend
cd backend
python -m uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm run dev
```

Open http://localhost:5173

## API Documentation
http://127.0.0.1:8000/docs (when backend is running)

## AWS Configuration
Set in `backend/.env`:
```
AWS_BEARER_TOKEN=<your-bedrock-token>
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
```

## Demo Flow
1. Enter trip details (destination, budget, travelers, days)
2. Get smart budget breakdown across categories
3. See real-time scraped prices for transport & hotels
4. Chat with AWS Bedrock AI copilot for optimizations
5. Get activity recommendations staying within budget

---

**Built for AWS Hackathon 2026** 🚀  
Real AI solving real travel planning problems.
