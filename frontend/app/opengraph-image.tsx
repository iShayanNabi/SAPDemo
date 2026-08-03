import { ImageResponse } from 'next/og';
import { BRAND_COLORS, ICON_BARS } from '@/lib/brand';
import { SOCIAL_IMAGE, canonicalOrigin } from '@/lib/metadata';

/**
 * The social preview card.
 *
 * Generated at build time by satori through the Next file convention, so Next
 * emits `og:image`, `og:image:width`, `og:image:height` and `og:image:alt`
 * itself and resolves the URL against `metadataBase`. That is the whole reason
 * `metadataBase` has to be the public origin: a preview URL a crawler cannot
 * fetch shows as a broken card, and a broken card is indistinguishable from no
 * card at all.
 *
 * What it deliberately is **not** is a screenshot. Nothing in this project has
 * a customer, a result or a deployment worth photographing, and an invented
 * dashboard on a preview card is the most widely-seen lie a demonstration site
 * can tell. It is a wordmark, a sentence about what the project is, and the
 * standing disclaimer - no address, no URL of a private service, no data.
 *
 * The type hierarchy is size and colour rather than weight: satori renders with
 * the single font Next bundles, so a `fontWeight: 700` that silently falls back
 * to regular would leave a card whose "bold" heading is not bold. Nothing here
 * depends on a weight being honoured.
 */
export const alt = SOCIAL_IMAGE.alt;
export const size = { width: SOCIAL_IMAGE.width, height: SOCIAL_IMAGE.height };
export const contentType = SOCIAL_IMAGE.contentType;

/** The domain, without the scheme - the form a person reads on a card. */
function displayDomain(): string {
  return canonicalOrigin.replace(/^https?:\/\//, '');
}

export default function OpengraphImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          backgroundColor: BRAND_COLORS.slate950,
          backgroundImage: `linear-gradient(135deg, ${BRAND_COLORS.slate900} 0%, ${BRAND_COLORS.slate950} 55%, #082f49 100%)`,
          padding: '72px 80px',
          fontFamily: 'sans-serif',
        }}
      >
        {/* The mark, and the parent brand beside it. */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 20 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-end',
              justifyContent: 'center',
              gap: 5,
              width: 64,
              height: 64,
              borderRadius: 14,
              background: BRAND_COLORS.slate800,
              paddingBottom: 14,
            }}
          >
            {ICON_BARS.map((bar) => (
              <div
                key={bar.fill}
                style={{
                  width: 8,
                  height: bar.height,
                  borderRadius: 3,
                  background: bar.fill,
                }}
              />
            ))}
          </div>
          <div
            style={{
              display: 'flex',
              fontSize: 30,
              letterSpacing: 2,
              textTransform: 'uppercase',
              color: BRAND_COLORS.slate400,
            }}
          >
            Solve AI Hub
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <div
            style={{
              display: 'flex',
              fontSize: 82,
              lineHeight: 1.05,
              color: BRAND_COLORS.white,
              letterSpacing: -2,
            }}
          >
            Procurement Intelligence Demo
          </div>
          <div
            style={{
              display: 'flex',
              marginTop: 14,
              fontSize: 38,
              color: BRAND_COLORS.sky400,
            }}
          >
            by Solve AI Hub
          </div>
          <div
            style={{
              display: 'flex',
              marginTop: 26,
              fontSize: 30,
              lineHeight: 1.4,
              color: BRAND_COLORS.slate300,
              maxWidth: 900,
            }}
          >
            Ten procurement and supply-chain tools. Rules and calculations decide; AI only
            explains.
          </div>
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderTop: `2px solid ${BRAND_COLORS.slate800}`,
            paddingTop: 26,
            fontSize: 24,
            color: BRAND_COLORS.slate400,
          }}
        >
          <div style={{ display: 'flex' }}>{displayDomain()}</div>
          <div style={{ display: 'flex' }}>
            Fictional demonstration data · Not affiliated with SAP
          </div>
        </div>
      </div>
    ),
    size,
  );
}
