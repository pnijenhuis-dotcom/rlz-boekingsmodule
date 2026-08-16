import * as React from 'react'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { cn } from './cn'

/* Dialog — Radix op zijn plek: focus-trap, Escape, aria-modal en scroll-lock gratis.
 * Vormgeving = mockup/kantoor-modern.html .modal-bg/.modal. */
export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close

export function DialogContent({
  className,
  children,
  breed,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
  /** Bredere variant voor tabellen/verdeel-modals. */
  breed?: boolean
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-60 grid place-items-center overflow-y-auto bg-[rgba(10,16,15,0.5)] p-4 backdrop-blur-[2px]">
        <DialogPrimitive.Content
          className={cn(
            'w-full rounded-[14px] border border-border bg-panel p-[22px] text-text shadow-zweef focus:outline-none',
            breed ? 'max-w-[720px]' : 'max-w-[480px]',
            className,
          )}
          {...props}
        >
          {children}
        </DialogPrimitive.Content>
      </DialogPrimitive.Overlay>
    </DialogPrimitive.Portal>
  )
}

export function DialogTitle({ className, ...props }: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>) {
  return <DialogPrimitive.Title className={cn('m-0 mb-1 text-[15px] font-bold', className)} {...props} />
}

export function DialogDescription({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description className={cn('m-0 mb-4 text-[12.5px] text-muted', className)} {...props} />
  )
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mt-[18px] flex justify-end gap-2', className)} {...props} />
}
