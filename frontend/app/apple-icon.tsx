import { ImageResponse } from 'next/og';
import { BRAND_COLORS, ICON_BARS } from '@/lib/brand';

/**
 * The same mark as `app/icon.svg`, rendered as a PNG for iOS.
 *
 * Safari's home-screen icon does not accept SVG, so this one has to be a
 * raster. It is generated at build time from the shared bar geometry rather
 * than being a committed bitmap: two files drawing the same mark by hand is how
 * an icon ends up updated in one place and not the other.
 *
 * 180×180 is the size iOS asks for. No `manifest.json` is added alongside it -
 * this site is a set of documents, and a manifest would invite an install
 * prompt and a service worker that nothing here needs.
 */
export const size = { width: 180, height: 180 };
export const contentType = 'image/png';

export default function AppleIcon() {
  const scale = size.width / 64;

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'center',
          gap: 6 * scale,
          background: BRAND_COLORS.slate900,
          paddingBottom: 14 * scale,
        }}
      >
        {ICON_BARS.map((bar) => (
          <div
            key={bar.fill}
            style={{
              width: 8 * scale,
              height: bar.height * scale,
              borderRadius: 3 * scale,
              background: bar.fill,
            }}
          />
        ))}
      </div>
    ),
    size,
  );
}
