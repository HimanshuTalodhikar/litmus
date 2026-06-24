# Phase 4 — Scale & Enterprise: Multi-Workspace, HA, and Compliance (Weeks 37–48)

**Goal:** Production hardening at scale — support multiple Slack workspaces, ensure HA, add enterprise security, and establish formal SLA guarantees.

**Cloud:** AWS (primary) + GCP Vertex AI + Qdrant Cloud

---

## Scope

### In Scope

- Multi-workspace support (multiple Slack workspaces)
- Multi-region ECS deployment (primary + failover)
- Enterprise SSO / SAML
- Audit logging with CloudWatch Logs + CloudTrail
- Advanced rate limiting and quota management per workspace
- Cost attribution per workspace
- Security hardening: VPC endpoints, IAM, WAF
- Disaster recovery testing and runbooks
- Load testing

### Out of Scope

- Additional AI capabilities (Phase 5)

---

## Deliverables

### 1. Multi-Workspace Support

```python
# backend/services/workspace_manager.py
class Workspace:
    id: UUID
    slack_team_id: str
    bot_token_ref: str          # Secrets Manager path
    knowledge_scope: str        # "workspace" | "enterprise_shared"
    rate_limit_config: dict
    jira_project_key: str
    owners: list[str]
```

```hcl
# infra/terraform/multi_workspace.tf
resource "aws_secretsmanager_secret" "workspace_bot_token" {
  for_each = toset(var.workspace_ids)
  name     = "product-copilot/slack-token-${each.value}"
}

resource "aws_dynamodb_table" "workspaces" {
  name           = "product-copilot-workspaces"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "workspace_id"

  attribute {
    name = "workspace_id"
    type = "S"
  }

  attribute {
    name = "slack_team_id"
    type = "S"
  }
}
```

### 2. Multi-Region ECS Deployment

```hcl
# infra/terraform/ecs_multi_region.tf

# Primary region (us-east-1)
resource "aws_ecs_service" "backend_primary" {
  name            = "product-copilot-backend-primary"
  cluster         = aws_ecs_cluster.primary.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = 2
  # ... load balancer config
}

# Secondary region (us-west-2)
resource "aws_ecs_cluster" "secondary" {
  name = "product-copilot-${var.project_env}-secondary"
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_route53_record" "backend" {
  name    = "api.productcopilot.ai"
  type    = "A"
  failover_routing_policy {
    type             = "FAILOVER"
    secondary_record {
      evaluate_target_health = true
      route {
        dns_name     = aws_elb.backend_secondary.dns_name
        set_identifier = "secondary"
      }
    }
  }
  set_identifier  = "primary"
  zone_id         = aws_route53_zone.main.zone_id
  alias {
    dns_name      = aws_lb.backend_primary.dns_name
    zone_id       = aws_lb.backend_primary.zone_id
    evaluate_target_health = true
  }
}
```

### 3. Enterprise SSO

```hcl
# infra/terraform/sso.tf

# AWS IAM Identity Center (recommended for AWS-native SSO)
resource "aws_ssoadmin_permission_set" "workspace_admin" {
  name         = "ProductCopilotWorkspaceAdmin"
  instance_arn = data.aws_ssoadmin_instances.main.instance_arns[0]

  permissions_boundary {
    managed_policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
  }
}

# SAML IdP: Okta, Azure AD, Google Workspace
# Configure in AWS SSO portal
```

### 4. CloudWatch Audit Logging

```python
# backend/services/audit_logger.py
import cloudwatch
import json
from datetime import datetime

def write_audit_log(
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str,
    workspace_id: str,
    details: dict = None,
):
    client = cloudwatchLogs.client()
    client.put_log_events(
        logGroupName="/aws/ecs/product-copilot/audit",
        logStreamName=f"{workspace_id}/{datetime.utcnow():%Y-%m-%d}",
        logEvents=[{
            "timestamp": int(datetime.utcnow().timestamp() * 1000),
            "message": json.dumps({
                "actor": actor,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "workspace_id": workspace_id,
                "details": details,
            })
        }]
    )
```

### 5. CloudWatch WAF + Rate Limiting

```hcl
# infra/terraform/waf.tf

resource "aws_wafv2_web_acl" "backend" {
  name  = "product-copilot-backend-acl"
  scope = "REGIONAL"

  rule_group_reference {
    arn = aws_wafv2_rule_group.rate_limit.arn
  }

  default_action {
    allow {}
  }
}

resource "aws_wafv2_rule_group" "rate_limit" {
  name  = "product-copilot-rate-limits"
  scope = "REGIONAL"

  rule {
    name     = "per-workspace-rate-limit"
    priority = 1
    action {
      block {
        custom_response {
          response_code = 429
          body          = jsonencode({"error": "Rate limit exceeded"})
        }
      }
    }
    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }
  }
}
```

---

## Success Criteria

- 10+ workspaces supported
- HA failover < 5min RTO
- SSO integrated (Okta or Azure AD)
- Audit logs queryable for 90+ days
- Load test: 200 concurrent users, < 1% error rate, p95 < 10s
