class InvalidRefreshTokenError(Exception):
    def __init__(self, instance_name: str):
        self.instance_name = instance_name
        super().__init__(f"Invalid refresh token for instance {instance_name}")
