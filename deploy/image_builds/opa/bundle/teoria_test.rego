package teoria.authz_test

import data.teoria.authz.decision

test_public_capability_is_allowed_when_permissions_match if {
    decision with input as {
        "principal": {
            "actor": "user:test",
            "authenticated": true,
            "roles": ["procurement_reader"],
        },
        "action": "capability.execute",
        "resource": {
            "exposure": "public",
            "required_permissions": ["procurement_reader"],
        },
    } == {
        "allow": true,
        "reason": "policy_allow",
        "metadata": {"policy_package": "teoria.authz"},
    }
}

test_capability_is_denied_when_permission_is_missing if {
    not decision.allow with input as {
        "principal": {
            "actor": "user:test",
            "authenticated": true,
            "roles": [],
        },
        "action": "capability.execute",
        "resource": {
            "exposure": "public",
            "required_permissions": ["procurement_reader"],
        },
    }
}

test_anonymous_context_plan_is_denied if {
    not decision.allow with input as {
        "principal": {
            "actor": "anonymous",
            "authenticated": true,
            "roles": [],
        },
        "action": "context.plan",
        "resource": {},
    }
}
