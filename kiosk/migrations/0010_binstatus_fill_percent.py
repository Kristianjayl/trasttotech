from django.db import migrations, models


def copy_existing_full_status(apps, schema_editor):
    BinStatus = apps.get_model("kiosk", "BinStatus")
    BinStatus.objects.filter(is_full=True).update(fill_percent=100)


class Migration(migrations.Migration):

    dependencies = [
        ("kiosk", "0009_kioskuser_hotspot_presence"),
    ]

    operations = [
        migrations.AddField(
            model_name="binstatus",
            name="fill_percent",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (0, "Empty"),
                    (25, "25%"),
                    (50, "50%"),
                    (100, "Full"),
                ],
                default=0,
            ),
        ),
        migrations.RunPython(
            copy_existing_full_status,
            migrations.RunPython.noop,
        ),
    ]
