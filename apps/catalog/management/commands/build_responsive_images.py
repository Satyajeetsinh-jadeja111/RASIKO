from django.core.management.base import BaseCommand

from apps.catalog.models import ProductImage


class Command(BaseCommand):
    help = "Generate 320/640px WebP derivatives for existing product images without derivatives."

    def handle(self, *args, **options):
        count = 0
        for image in ProductImage.objects.filter(responsive_images={}).iterator(chunk_size=50):
            image.build_responsive_images()
            count += 1
        self.stdout.write(f"Generated responsive images for {count} products.")
