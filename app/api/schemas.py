from marshmallow import Schema, fields, validate, validates, ValidationError
from croniter import croniter


class CreateJobSchema(Schema):
    # required fields
    name = fields.Str(required=True, validate=validate.Length(min=1, max=255))
    job_type = fields.Str(required=True)
    schedule_type = fields.Str(
        required=True,
        validate=validate.OneOf(["periodic", "one_time"])
    )

    # optional fields with sensible defaults
    cron_expression = fields.Str(load_default=None)
    payload = fields.Dict(load_default=None)
    priority = fields.Str(
        load_default="normal",
        validate=validate.OneOf(["high", "normal", "low"])
    )
    max_retries = fields.Int(load_default=3, validate=validate.Range(min=0, max=10))
    max_execution_time = fields.Int(load_default=300, validate=validate.Range(min=5))
    max_concurrency = fields.Int(load_default=1, validate=validate.Range(min=1))
    failure_threshold = fields.Float(load_default=0.5, validate=validate.Range(min=0.0, max=1.0))
    alert_webhook = fields.Str(load_default=None)

    @validates("cron_expression")
    def validate_cron(self, value):
      
        if value is not None and not croniter.is_valid(value):
            raise ValidationError(f"Invalid cron expression: {value}")


class UpdateJobSchema(Schema):
    # all fields optional for update
    name = fields.Str(validate=validate.Length(min=1, max=255))
    payload = fields.Dict()
    priority = fields.Str(validate=validate.OneOf(["high", "normal", "low"]))
    max_retries = fields.Int(validate=validate.Range(min=0, max=10))
    max_execution_time = fields.Int(validate=validate.Range(min=5))
    max_concurrency = fields.Int(validate=validate.Range(min=1))
    failure_threshold = fields.Float(validate=validate.Range(min=0.0, max=1.0))
    alert_webhook = fields.Str()
    cron_expression = fields.Str()

    @validates("cron_expression")
    def validate_cron(self, value):
        if value is not None and not croniter.is_valid(value):
            raise ValidationError(f"Invalid cron expression: {value}")