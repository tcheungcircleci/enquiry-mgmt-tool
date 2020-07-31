# Generated by Django 3.0.7 on 2020-08-04 11:42

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('enquiries', '0015_remove_cyber_from_sectors_ref_data'),
    ]

    operations = [
        migrations.AlterField(
            model_name='enquiry',
            name='enquiry_stage',
            field=models.CharField(choices=[('NEW', 'New'), ('AWAITING_RESPONSE', 'Awaiting response from Investor'), ('ENGAGED', 'Engaged in dialogue'), ('NON_RESPONSIVE', 'Non-responsive'), ('NON_FDI', 'Non-FDI'), ('ADDED_TO_DATAHUB', 'Added to Data Hub'), ('SENT_TO_POST', 'Sent to Post'), ('POST_PROGRESSING', 'Post progressing'), ('NON_APPLICABLE', 'Non-applicable')], default='NEW', max_length=255, verbose_name='Enquiry stage'),
        ),
    ]
