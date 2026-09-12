"use client";

/**
 * react-hook-form <-> shadcn bridge.
 *
 * shadcn's Base UI style does not ship `form` in its registry, so this is the
 * standard Form/FormField/FormItem/FormControl/FormMessage API written against
 * the Label primitive that IS installed.
 *
 * What it buys, and why it is worth a file: every field gets a generated id
 * wired through htmlFor / aria-describedby / aria-invalid automatically. Doing
 * that by hand on a twelve-field form is where accessibility silently rots —
 * one forgotten aria-describedby and a screen reader never announces the
 * validation error.
 */

import * as React from "react";
import {
  Controller,
  FormProvider,
  useFormContext,
  useFormState,
  type ControllerProps,
  type FieldPath,
  type FieldValues,
} from "react-hook-form";
import { cn } from "cn";

import { Label } from "@/components/ui/label";

const Form = FormProvider;

type FormFieldContextValue<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
> = { name: TName };

const FormFieldContext = React.createContext<FormFieldContextValue>(
  {} as FormFieldContextValue,
);

function FormField<
  TFieldValues extends FieldValues = FieldValues,
  TName extends FieldPath<TFieldValues> = FieldPath<TFieldValues>,
>({ ...props }: ControllerProps<TFieldValues, TName>) {
  return (
    <FormFieldContext.Provider value={{ name: props.name }}>
      <Controller {...props} />
    </FormFieldContext.Provider>
  );
}

type FormItemContextValue = { id: string };
const FormItemContext = React.createContext<FormItemContextValue>(
  {} as FormItemContextValue,
);

function useFormField() {
  const fieldContext = React.useContext(FormFieldContext);
  const itemContext = React.useContext(FormItemContext);
  const { getFieldState } = useFormContext();
  const formState = useFormState({ name: fieldContext.name });
  const fieldState = getFieldState(fieldContext.name, formState);

  if (!fieldContext) {
    throw new Error("useFormField must be used within <FormField>");
  }

  const { id } = itemContext;
  return {
    id,
    name: fieldContext.name,
    formItemId: `${id}-form-item`,
    formDescriptionId: `${id}-form-item-description`,
    formMessageId: `${id}-form-item-message`,
    ...fieldState,
  };
}

function FormItem({ className, ...props }: React.ComponentProps<"div">) {
  const id = React.useId();
  return (
    <FormItemContext.Provider value={{ id }}>
      <div data-slot="form-item" className={cn("grid gap-2", className)} {...props} />
    </FormItemContext.Provider>
  );
}

function FormLabel({ className, ...props }: React.ComponentProps<typeof Label>) {
  const { error, formItemId } = useFormField();
  return (
    <Label
      data-slot="form-label"
      data-error={!!error}
      // Errors are never signalled by colour alone — FormMessage below carries
      // the text, and aria-invalid carries it to assistive tech.
      className={cn("data-[error=true]:text-destructive font-bold", className)}
      htmlFor={formItemId}
      {...props}
    />
  );
}

function FormControl({ ...props }: React.ComponentProps<"div">) {
  const { error, formItemId, formDescriptionId, formMessageId } = useFormField();
  return (
    <Slot
      data-slot="form-control"
      id={formItemId}
      aria-describedby={
        !error ? formDescriptionId : `${formDescriptionId} ${formMessageId}`
      }
      aria-invalid={!!error}
      {...props}
    />
  );
}

/** Minimal Slot: merges props onto a single child element. */
function Slot({ children, ...props }: React.ComponentProps<"div">) {
  if (!React.isValidElement(children)) return null;
  return React.cloneElement(children as React.ReactElement<Record<string, unknown>>, {
    ...props,
    ...(children.props as Record<string, unknown>),
    // Our generated ids/aria must win over whatever the child declared,
    // otherwise the label and the error message point at nothing.
    id: (props as { id?: string }).id,
    "aria-describedby": (props as { "aria-describedby"?: string })["aria-describedby"],
    "aria-invalid": (props as { "aria-invalid"?: boolean })["aria-invalid"],
  });
}

function FormDescription({ className, ...props }: React.ComponentProps<"p">) {
  const { formDescriptionId } = useFormField();
  return (
    <p
      data-slot="form-description"
      id={formDescriptionId}
      className={cn("text-sm text-muted-foreground", className)}
      {...props}
    />
  );
}

function FormMessage({ className, ...props }: React.ComponentProps<"p">) {
  const { error, formMessageId } = useFormField();
  const body = error ? String(error?.message ?? "") : props.children;
  if (!body) return null;

  return (
    <p
      data-slot="form-message"
      id={formMessageId}
      // Errors sit next to their field, not collected at the top of the form.
      className={cn("text-sm font-bold text-destructive", className)}
      {...props}
    >
      {body}
    </p>
  );
}

export {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  useFormField,
};
