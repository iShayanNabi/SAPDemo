import Link from 'next/link';
import { siteConfig } from '@/lib/site';

/**
 * A text-based logo placeholder, and the one home link on the page.
 *
 * Deliberately typographic rather than a mark: a placeholder image would either
 * be a shape nobody chose or a borrowed one, and this project must not carry
 * anybody else's brand assets. Replacing this with a real logo is a change to
 * this one component.
 *
 * **The space in "Solve AI Hub" is a real space.** The two-tone wordmark used
 * to be two adjacent spans in a flex row with `gap-1` between them, which
 * *looks* right and is not: a flex gap is a layout property, not a character,
 * so the brand's text was `Solve AIHub` everywhere text is read rather than
 * painted - copy and paste, a text-only client, a search of the built HTML for
 * the brand name. It is now one `Solve AI Hub` string with the colour change
 * around a word, held on one line by `whitespace-nowrap`, so the phrase can
 * neither collapse into `SolveAI Hub` nor wrap into two lines mid-brand.
 *
 * The header shows the parent brand alone - the product name is too long to
 * sit in a sticky header next to eight links - and the accessible name carries
 * both, so a screen-reader user hears what the site is rather than only who
 * publishes it. `withProductName` prints the product line where there is room:
 * the footer.
 */
export function Logo({
  className = '',
  withProductName = false,
}: {
  className?: string;
  withProductName?: boolean;
}) {
  return (
    <Link
      href="/"
      /*
       * `inline-block` with block children rather than a flex column. A flex
       * container discards a whitespace-only child, and the separator below
       * has to survive into `textContent` - see the comment on it.
       */
      className={`group inline-block rounded-sm font-semibold leading-tight tracking-tight focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600 ${className}`}
      aria-label={`${siteConfig.fullName} home`}
    >
      <span className="block whitespace-nowrap">
        <span className="text-slate-900 dark:text-white">Solve AI</span>{' '}
        <span className="text-sky-600 dark:text-sky-400">Hub</span>
      </span>
      {withProductName ? (
        <>
          {/*
            A real space between the two lines of the lockup. They are separate
            block boxes, so this renders nothing at all - white space between
            block-level boxes is not painted - but it is a character in
            `textContent`, and without it the brand and the product name
            concatenate into `Solve AI HubProcurement Intelligence Demo` for
            anything that reads the page as text.
          */}
          {' '}
          <span
            aria-hidden="true"
            className="mt-1 block text-xs font-medium tracking-normal text-slate-600 dark:text-slate-400"
          >
            {siteConfig.name}
          </span>
        </>
      ) : null}
    </Link>
  );
}
