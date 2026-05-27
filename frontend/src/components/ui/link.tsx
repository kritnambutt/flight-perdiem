import * as Headless from '@headlessui/react'
import React, { forwardRef } from 'react'
import { Link as RouterLink } from 'react-router-dom'

export const Link = forwardRef(function Link(
  { href, ...props }: { href: string } & Omit<React.ComponentPropsWithoutRef<'a'>, 'href'>,
  ref: React.ForwardedRef<HTMLAnchorElement>
) {
  const isExternal =
    href.startsWith('http') || href.startsWith('//') || href.startsWith('mailto:')
  return (
    <Headless.DataInteractive>
      {isExternal ? (
        <a href={href} {...props} ref={ref} />
      ) : (
        <RouterLink to={href} {...(props as React.ComponentPropsWithoutRef<'a'>)} ref={ref} />
      )}
    </Headless.DataInteractive>
  )
})
