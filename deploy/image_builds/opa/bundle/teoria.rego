package teoria.authz

default allow := false

authenticated if {
    input.principal.authenticated == true
}

required_permissions := object.get(input.resource, "required_permissions", [])

permissions_satisfied if {
    every permission in required_permissions {
        permission in input.principal.roles
    }
}

allow if {
    authenticated
    input.action in {"runtime.version.read", "capability.discover"}
}

allow if {
    authenticated
    input.action == "capability.execute"
    input.resource.exposure == "public"
    permissions_satisfied
}

allow if {
    authenticated
    input.action in {"context.plan", "context.execute"}
    input.principal.actor != "anonymous"
}

default reason := "default_deny"

reason := "policy_allow" if {
    allow
}

decision := {
    "allow": allow,
    "reason": reason,
    "metadata": {"policy_package": "teoria.authz"},
}
