from rakit_core.integrations import IntegrationDescriptor

AUTH_SQLALCHEMY_INTEGRATION = IntegrationDescriptor(
    integration_id="auth.sqlalchemy",
    category="authentication",
    display_name="SQLAlchemy authentication",
)

__all__ = ["AUTH_SQLALCHEMY_INTEGRATION"]
