// Package apperr defines typed application errors that the HTTP layer maps
// to status codes in one place, so every handler doesn't hand-roll its own
// status-code decisions (a common source of authorization bugs).
package apperr

import "errors"

type Kind string

const (
	KindNotFound     Kind = "not_found"
	KindForbidden    Kind = "forbidden"
	KindUnauthorized Kind = "unauthorized"
	KindConflict     Kind = "conflict"
	KindInvalid      Kind = "invalid"
	KindInternal     Kind = "internal"
)

type Error struct {
	Kind    Kind
	Message string
	Err     error
}

func (e *Error) Error() string {
	if e.Err != nil {
		return e.Message + ": " + e.Err.Error()
	}
	return e.Message
}

func (e *Error) Unwrap() error { return e.Err }

func New(kind Kind, message string) *Error { return &Error{Kind: kind, Message: message} }

func Wrap(kind Kind, message string, err error) *Error {
	return &Error{Kind: kind, Message: message, Err: err}
}

func NotFound(message string) *Error     { return New(KindNotFound, message) }
func Forbidden(message string) *Error    { return New(KindForbidden, message) }
func Unauthorized(message string) *Error { return New(KindUnauthorized, message) }
func Conflict(message string) *Error     { return New(KindConflict, message) }
func Invalid(message string) *Error      { return New(KindInvalid, message) }
func Internal(err error) *Error          { return Wrap(KindInternal, "internal error", err) }

func As(err error) (*Error, bool) {
	var e *Error
	if errors.As(err, &e) {
		return e, true
	}
	return nil, false
}
