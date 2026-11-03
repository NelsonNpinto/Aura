# Terraform practice

This optional local-Docker example provisions an isolated pgvector database on port 5435. It does not create paid cloud resources or replace the application Compose stack. Nothing is applied automatically.

```sh
export TF_VAR_postgres_password="$(openssl rand -hex 24)"
terraform init
terraform fmt -check
terraform validate
terraform plan
# Review the plan before terraform apply.
```

Terraform state includes environment variables, including the database password. Keep local state private; use an encrypted remote state backend for a team deployment. State and plan files are ignored by Git. Removing a database volume destroys its data: inspect a destroy plan and take a backup before teardown.
