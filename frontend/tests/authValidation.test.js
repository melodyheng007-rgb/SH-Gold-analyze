import test from 'node:test'
import assert from 'node:assert/strict'

import { normalizeEmail, validateAuthForm } from '../src/auth/authValidation.js'

test('email normalization is stable for authentication requests', () => {
  assert.equal(normalizeEmail('  User@Example.COM  '), 'user@example.com')
})

test('login requires a valid email and an eight-character password', () => {
  assert.equal(validateAuthForm('login', { email: 'bad', password: '12345678' }), 'Enter a valid email address.')
  assert.equal(validateAuthForm('login', { email: 'user@example.com', password: 'short' }), 'Password must contain at least 8 characters.')
  assert.equal(validateAuthForm('login', { email: 'user@example.com', password: 'correct12' }), '')
})

test('registration requires a name and matching passwords', () => {
  assert.equal(validateAuthForm('register', {
    fullName: 'S',
    email: 'user@example.com',
    password: 'correct12',
    confirmPassword: 'correct12',
  }), 'Enter your full name.')
  assert.equal(validateAuthForm('register', {
    fullName: 'SH User',
    email: 'user@example.com',
    password: 'correct12',
    confirmPassword: 'different12',
  }), 'Passwords do not match.')
})

test('forgot password validates email without requiring a password', () => {
  assert.equal(validateAuthForm('forgot', { email: 'user@example.com' }), '')
})

test('email confirmation requires a six-digit code', () => {
  assert.equal(validateAuthForm('verify-signup', { otp: '12345' }), 'Enter the 6-digit confirmation code.')
  assert.equal(validateAuthForm('verify-recovery', { otp: '123456' }), '')
})
