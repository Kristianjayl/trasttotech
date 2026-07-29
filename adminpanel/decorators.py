from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from functools import wraps


def role_required(*allowed_roles):
    """
    Usage: @role_required('admin')  -> only Admins can access
           @role_required('admin', 'sk')  -> both roles can access (same as just @login_required)

    Put this ABOVE @login_required on any view once you decide which
    pages should be restricted -- nothing is locked down yet except
    what you explicitly mark.
    """
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapped(request, *args, **kwargs):
            profile = getattr(request.user, "staffprofile", None)
            if not profile or profile.role not in allowed_roles:
                raise PermissionDenied("You don't have access to this page.")
            return view_func(request, *args, **kwargs)
        return wrapped
    return decorator