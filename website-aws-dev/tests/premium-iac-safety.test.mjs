// Authorization contracts for the deployed Premium API; no AWS access.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = file => readFileSync(new URL('../../infra/aws/' + file, import.meta.url), 'utf8');
const api = read('api.tf');
const iam = read('iam.tf');
const variables = read('variables.tf');

function block(source, header) {
  const start = source.indexOf(header + ' {');
  assert.notEqual(start, -1, 'Missing required Terraform block: ' + header);
  const end = source.indexOf('\n}', start);
  assert.notEqual(end, -1, 'Missing end of Terraform block: ' + header);
  return source.slice(start, end + 2);
}

test('Premium account and admin routes inherit JWT authorization', () => {
  const routeList = api.match(/authenticated_routes\s*=\s*toset\(\[([\s\S]*?)\]\)/)?.[1];
  assert.ok(routeList, 'Authenticated route set is required');
  const routes = [...routeList.matchAll(/"([^"\n]+)"/g)].map(match => match[1]);
  for (const route of ['GET /me', 'GET /admin/users', 'POST /admin/users/{sub}/premium']) {
    assert.equal(routes.filter(value => value === route).length, 1, route);
  }
  const routeResource = block(api, 'resource "aws_apigatewayv2_route" "authenticated"');
  assert.match(routeResource, /for_each\s*=\s*local\.authenticated_routes/);
  assert.match(routeResource, /authorization_type\s*=\s*"JWT"/);
  assert.match(routeResource, /authorizer_id\s*=\s*aws_apigatewayv2_authorizer\.cognito\.id/);
  const authorizer = block(api, 'resource "aws_apigatewayv2_authorizer" "cognito"');
  assert.match(authorizer, /audience\s*=\s*\[aws_cognito_user_pool_client\.web\.id\]/);
  assert.match(authorizer, /issuer\s*=\s*"https:\/\/cognito-idp\./);
});

test('API identity permissions are read-only and restricted to the current pool', () => {
  const policy = block(iam, 'data "aws_iam_policy_document" "api"');
  const identityStatements = [...policy.matchAll(/statement\s*\{([\s\S]*?)\n  \}/g)]
    .map(match => match[1]).filter(statement => statement.includes('cognito-idp:'));
  assert.equal(identityStatements.length, 1);
  const statement = identityStatements[0];
  const actions = [...statement.matchAll(/"(cognito-idp:[^"\n]+)"/g)].map(match => match[1]).sort();
  assert.deepEqual(actions, ['cognito-idp:AdminGetUser', 'cognito-idp:ListUsers']);
  assert.match(statement, /resources\s*=\s*\[aws_cognito_user_pool\.users\.arn\]/);
  assert.doesNotMatch(statement, /resources\s*=\s*\["\*"\]/);
});

test('Premium owner configuration cannot activate GPU jobs or billing', () => {
  const lambda = block(api, 'resource "aws_lambda_function" "api"');
  assert.match(lambda, /COGNITO_USER_POOL_ID\s*=\s*aws_cognito_user_pool\.users\.id/);
  assert.match(lambda, /PREMIUM_OWNER_SUB\s*=\s*var\.premium_owner_sub/);
  assert.match(lambda, /ADMIN_COGNITO_SUBS\s*=\s*join\(",", var\.admin_cognito_subs\)/);
  assert.match(lambda, /PAID_GPU_ENABLED\s*=\s*"false"/);
  assert.match(lambda, /PAID_BILLING_ENABLED\s*=\s*"false"/);
  assert.doesNotMatch(lambda, /(?:GPU_DISPATCH_READY|GPU_DISPATCH_ENABLED)\s*=\s*(?!"false")\S+/);
  const owner = block(variables, 'variable "premium_owner_sub"');
  assert.match(owner, /default\s*=\s*""/);
  assert.match(owner, /sensitive\s*=\s*true/);
  assert.match(owner, /contains\(var\.admin_cognito_subs, var\.premium_owner_sub\)/);
  // Existing CPU inputs continue to control the free service independently.
  assert.match(lambda, /CPU_BATCH_JOB_QUEUE\s*=\s*var\.enable_cpu_analysis \?/);
});
