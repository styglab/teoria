package system.log

# Capability and Context inputs can contain provider identifiers or future
# sensitive values. Keep actor, action, resource, result and bundle revision,
# but remove execution inputs before telemetry leaves OPA.
mask contains "/input/context/inputs"
