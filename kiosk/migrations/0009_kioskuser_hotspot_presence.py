from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("kiosk", "0008_bottlescan"),
    ]

    operations = [
        migrations.AddField(
            model_name="kioskuser",
            name="last_ip",
            field=models.GenericIPAddressField(
                blank=True,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="kioskuser",
            name="last_seen_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
            ),
        ),
    ]
