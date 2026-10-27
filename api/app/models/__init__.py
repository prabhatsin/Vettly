from app.models.user import User, UserRole

# This makes sure the model is imported whenever app.models is, so Alembic’s autogenerate can see it. 
# That is the “import your models there” part of the plan.

