# Slack AI Assistant

Intelligent Slack bot that answers company questions by retrieving and analyzing documents stored in S3, powered by Claude. Drop PDFs, Word docs, or text files into S3, mention the bot in Slack, and get instant answers grounded in your company knowledge base.

Built as a reference implementation by [Three Moons Network](https://threemoonsnetwork.net) — an AI consulting practice helping small businesses automate with production-grade systems.

## What It Does

1. **Listen** for slash commands (`/ask`) or mentions (`@bot-name`) in Slack
2. **Retrieve** relevant documents from S3 using keyword matching
3. **Generate** context-aware answers using Claude
4. **Post** responses back to Slack with source citations
5. **Cache** conversations in DynamoDB for audit and context

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Slack Workspace                       │
│                                                             │
│  User: @bot-name What's our return policy?                │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                       AWS Cloud                            │
│                                                             │
│  API Gateway HTTP API ──┐                                  │
│                         ▼                                  │
│                      Lambda                                │
│                    (Event Handler)                         │
│                         │                                  │
│         ┌───────────────┼───────────────┐                 │
│         ▼               ▼               ▼                 │
│       S3 Bucket      Claude API    DynamoDB               │
│      (Docs:                      (Conversation            │
│       company                     cache)                   │
│       handbook,                                            │
│       FAQs, etc)                                           │
│         │                         │                       │
│         └────────────┬────────────┘                       │
│                      ▼                                    │
│                   Lambda                                  │
│              (Response Handler)                           │
│                      │                                    │
└──────────────────────┼──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Slack Channel                           │
│                                                             │
│  Bot: Based on our Return Policy document...              │
│       [answer with source citations]                     │
└─────────────────────────────────────────────────────────────┘
```

## Features

| Feature | Details |
|---------|---------|
| **Event Handling** | Handles slash commands, mentions, and thread replies |
| **Knowledge Retrieval** | Keyword-based document matching from S3 |
| **Claude Integration** | Uses Claude API for intelligent, context-aware answers |
| **Source Citations** | Automatically cites which documents were used |
| **Signature Verification** | Validates all Slack requests using HMAC-SHA256 |
| **Conversation Caching** | Stores Q&A in DynamoDB for audit and future context |
| **Error Handling** | Graceful degradation if knowledge base is empty |
| **Logging & Monitoring** | CloudWatch logs + alarms for errors and latency |

## Quick Start

### Prerequisites

- AWS account with CLI configured
- Terraform >= 1.5
- Python 3.11+
- Slack workspace where you can create/manage apps

### 1. Clone and setup

```bash
git clone git@github.com:Three-Moons-Network/slack-ai-assistant.git
cd slack-ai-assistant

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 2. Create Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click "Create New App" → "From scratch"
3. Name: "Company AI Assistant", Workspace: select yours
4. Go to "OAuth & Permissions"
5. Under "Scopes", add:
   - `chat:write` (post messages)
   - `users:read` (get user info)
6. Install app to workspace (copy **Bot User OAuth Token**)
7. Go to "App-Level Tokens" → "Generate Token"
   - Add `connections:write` scope
   - Copy the token (starts with `xapp-...`)
8. Go to "Event Subscriptions"
   - Enable events
   - For "Request URL", you'll use the API Gateway URL from Terraform (deploy first, then come back)
   - Subscribe to bot events:
     - `message.app_mention`
     - `app_mention`
   - Subscribe to slash commands:
     - Create a slash command `/ask` pointing to same URL

### 3. Configure Terraform

```bash
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
```

Edit `terraform/terraform.tfvars`:
```hcl
slack_bot_token      = "xoxb-..."    # From OAuth & Permissions
slack_signing_secret = "..."         # From Settings > App Credentials
anthropic_api_key    = "sk-ant-..."  # From console.anthropic.com
```

### 4. Build and deploy

```bash
./scripts/deploy.sh

cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

Terraform outputs the API endpoint. Copy it.

### 5. Configure Slack event subscription

1. Go back to your Slack app (api.slack.com/apps > your app)
2. Event Subscriptions → Request URL
3. Paste `<api-endpoint>/events`
4. Slack will verify the URL (must be HTTPS and respond within 3 seconds)

### 6. Upload knowledge base documents

Create a few sample documents and upload to S3:

```bash
# Get bucket name from Terraform output
BUCKET=$(cd terraform && terraform output -raw s3_bucket_name)

# Create a sample document
echo "Our return policy: Returns accepted within 30 days of purchase.
Contact support@company.com for returns." > return_policy.txt

# Upload to S3
aws s3 cp return_policy.txt "s3://$BUCKET/docs/"
```

### 7. Test it

In your Slack workspace:

```
@Company AI Assistant What's your return policy?
```

The bot should respond with the policy and cite "return_policy.txt" as the source.

## Project Structure

```
├── src/
│   ├── __init__.py
│   ├── handler.py              # Lambda handler — events, signature verification
│   ├── slack_client.py         # Slack SDK wrapper
│   └── knowledge.py            # S3 document retrieval, keyword matching
├── tests/
│   ├── __init__.py
│   ├── test_handler.py         # Handler tests (mocked Slack/Claude)
│   └── test_knowledge.py       # Knowledge base tests (mocked S3)
├── terraform/
│   ├── main.tf                 # All AWS infrastructure
│   ├── outputs.tf              # Output values
│   ├── backend.tf              # Remote state (commented for local use)
│   └── terraform.tfvars.example
├── .github/workflows/
│   └── ci.yml                  # Test, lint, validate, package
├── scripts/
│   └── deploy.sh               # Build Lambda package
├── requirements.txt            # Runtime: anthropic, slack-sdk, boto3
├── requirements-dev.txt        # Dev: pytest, ruff, moto
└── README.md                   # This file
```

## How It Works

### 1. Event Flow

```
Slack Event (mention or /ask)
    ↓
API Gateway receives POST to /events
    ↓
Lambda handler.py:lambda_handler()
    ├─ Verify Slack signature
    ├─ Parse event (slash command, app mention, thread reply)
    ├─ Retrieve relevant docs from S3
    ├─ Call Claude API with documents as context
    ├─ Post response back to Slack
    └─ Cache Q&A in DynamoDB
```

### 2. Document Retrieval

Simple **keyword matching**:
- Split user query into tokens (lowercase, remove stopwords, filter short words)
- Score each S3 document by token frequency
- Return top 3 matching documents
- Truncate each to first 2000 characters (fits in Claude context window)

No vector embeddings = no ML model, no extra cost, simple to understand.

### 3. Claude Integration

System prompt tells Claude to:
- Answer based on provided documentation
- Cite sources by document name
- Say "I don't know" if documentation doesn't answer the question
- Keep responses concise and professional

User sees final answer with source references like:
> Based on our Return Policy document...
> [answer]
> Sources: `return_policy.txt`

### 4. Conversation Caching

Each Q&A pair is stored in DynamoDB:
- Partition key: `conversation_id` (channel ID + timestamp)
- Range key: `timestamp`
- TTL: 30 days (auto-cleanup)
- Enables: audit trail, future context retrieval, analytics

## Customization

### Add Document Types

Store any document type in S3:
```bash
aws s3 cp employee_handbook.pdf "s3://$BUCKET/docs/"
aws s3 cp pricing.md "s3://$BUCKET/docs/"
aws s3 cp faqs.txt "s3://$BUCKET/docs/"
```

The handler auto-fetches and includes all documents matching your query.

### Change Max Documents Retrieved

Edit `src/handler.py`, in `lambda_handler()`:
```python
documents = knowledge_base.retrieve(slack_event.text, max_documents=5)  # Changed from 3
```

### Improve Document Matching

Replace keyword matching with vector similarity (requires additional infrastructure):

1. Generate embeddings for all documents using Claude API or local model
2. Store embeddings in DynamoDB or Pinecone
3. On query, embed the question and find cosine similarity matches
4. This handles synonyms and semantic relationships better

### Add Slack Formatting

Enhance responses with Block Kit (Slack's rich message format):

```python
blocks = [
    {
        "type": "section",
        "text": {"type": "mrkdwn", "text": response.answer},
    },
    {
        "type": "image",
        "image_url": "https://...",
        "alt_text": "diagram",
    },
]
slack_client.post_message(..., blocks=blocks)
```

## Cost Estimate

For low-volume usage (< 100 questions/day):

| Component | Estimated Monthly Cost |
|-----------|----------------------|
| Lambda | ~$0 (free tier: 1M requests) |
| API Gateway | ~$0 (free tier: 1M calls) |
| S3 | ~$0.50 (storage + retrieval) |
| DynamoDB | ~$1 (PAY_PER_REQUEST, low volume) |
| CloudWatch | ~$0.50 (log storage) |
| **Total Infrastructure** | **~$2-3/month** |
| **Claude API** | ~$1-10/month (depending on doc size + answer length) |

**Total: ~$3-13/month** for a small business knowledge base.

## Troubleshooting

### Bot doesn't respond to mentions

1. Check Lambda logs: `aws logs tail /aws/lambda/slack-ai-assistant-dev --follow`
2. Verify Slack event subscription is configured correctly
3. Make sure bot has `chat:write` permission
4. Check S3 bucket exists and contains documents

### "Invalid Slack signature" error

1. Verify `slack_signing_secret` is correct in `.tfvars`
2. Check Slack app credentials haven't been regenerated
3. Verify request timestamp is within 5 minutes

### Claude API errors

1. Check `anthropic_api_key` in `.tfvars` is valid
2. Verify API key has sufficient quota
3. Check Claude model name is correct in `terraform.tfvars`

### Documents not being found

1. Verify documents are uploaded to correct S3 prefix (`docs/`)
2. Check S3 bucket name in Lambda environment variables
3. Try uploading a test file with simple keywords
4. Check CloudWatch logs for retrieval errors

## Best Practices

1. **Organize documents** in S3 with consistent naming (`return_policy.txt`, `faq.md`, etc.)
2. **Keep documents focused** — one topic per file for better matching
3. **Test locally** with `pytest tests/ -v` before deploying
4. **Monitor costs** — set CloudWatch alarms for high Lambda duration or error rates
5. **Version your documents** — enable S3 versioning on knowledge base bucket
6. **Backup conversations** — export DynamoDB periodically for audit
7. **Review Slack logs** — periodically check what users ask to identify gaps

## License

MIT

## Author

Charles Harvey ([linuxlsr](https://github.com/linuxlsr)) — [Three Moons Network LLC](https://threemoonsnetwork.net)
