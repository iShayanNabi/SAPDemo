import type { ReactNode } from 'react';
import { repositoryLabel, siteConfig } from '@/lib/site';

/**
 * A link to the public source repository - or nothing at all.
 *
 * This project's repository is private, so `NEXT_PUBLIC_REPOSITORY_URL` is
 * unset in the deployment and every source link on the site has to disappear.
 * "Disappear" is the important word: an anchor with `href=""` is not a
 * disabled link, it is a link that silently reloads the page the visitor is
 * already on, and a greyed-out "Source on GitHub" still advertises a
 * repository nobody can open.
 *
 * Returning `null` rather than a placeholder is what makes the surrounding
 * layout collapse instead of leaving a gap. Callers that need to say something
 * different when there is no repository should branch on `hasRepository`
 * instead of wrapping this - a paragraph that reads "the source is public"
 * with the link removed is still making the claim.
 *
 * Configuring a valid `https://` URL brings every one of them back, with no
 * other change.
 */
export function RepositoryLink({
  children,
  className = 'font-medium text-sky-700 underline underline-offset-4 hover:text-sky-900 dark:text-sky-400 dark:hover:text-sky-300',
}: {
  /** Defaults to the repository address itself, without the scheme. */
  children?: ReactNode;
  className?: string;
}) {
  const href = siteConfig.repositoryUrl;
  if (!href) {
    return null;
  }

  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children ?? repositoryLabel()}
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}
