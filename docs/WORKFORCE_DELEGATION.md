# Time-limited workforce review authority

5 October 2026. This extends the existing financial approval matrix with four
explicit nonfinancial capabilities. A grant does not change a staff member's
role, groups, login privileges or clinical authority.

## Delegable operations

| Capability | Permitted work |
| --- | --- |
| Attendance review | Independently approve/reject corrections and review completed attendance |
| Leave review | Independently approve/reject requests and cancel approved leave |
| Cover and swap review | Independently approve/reject accepted shift cover and reciprocal swaps |
| Roster publication | Publish selected draft duties individually or as an atomic group |

These grants do not permit financial approvals, patient assignment, clinical
decisions, roster creation/cancellation, directory/employment/credential changes,
policy configuration, exports, account administration or further delegation.
Original manager/administrator permissions remain separate and unchanged.

## Administrator workflow

Open **Facility setup → Approval limits and timed delegation**. The workforce
form has no money amount. Choose the exact facility, operation, staff member,
start/end time and reason. The recipient must be active and actually assigned to
that facility; a selected branch session does not substitute for assignment.
The workforce module must be enabled. Configured employment must be currently
eligible; staff without an employment record retain the existing legacy eligibility.
Temporary owner-support identities cannot receive or manage authority, and
administrators cannot grant authority to themselves.

Intervals/reasons remain immutable. Revoke and issue a replacement when scope or
dates change. Existing request-key replay and overlap protections apply. Workforce
authority does not use or change the financial workflow policy switches.

## Staff workflow and safeguards

The existing duty, review-inbox, timesheet and publication screens expose only
the granted category. A leave grant does not expose other staff's attendance
correction reasons; an attendance grant does not expose unrelated leave reasons
or handover notes. Manager-only directory, policies, exports and administrative
controls remain unavailable.

Requests must still be reviewed by someone outside the request and its
participants. Both requesters and all participants are excluded from reciprocal
swap review. Replacement acceptance never substitutes for supervisor approval.
Roster publication retains its existing workflow: it is not independently
reviewed merely because an operation-specific grant is used.

Every mutation checks current authority after acquiring the facility lock.
Expiry, revocation, deactivation, reassignment or ineligible employment between
opening a form and submitting it removes delegated authority. Completed cover
and swap retries also require current permission. Grant revocation and delegated
use serialize on the same facility lock. Successful delegated changes record the
grant ID, operation and record alongside the existing workflow history.

Roster conflicts, leave, employment, coverage minima, revision checks and atomic
group publication still apply. Publication does not certify clinical competence,
legal working-time compliance or a clinically sufficient staffing ratio.

## Upgrade and verification

Apply accounts migration `0012_workforce_approval_authority` after the earlier
completion migrations. Existing monetary grants keep their amounts and behavior;
only workforce grants use a null monetary limit. A database constraint separates
the two kinds of authority.

Regression coverage includes direct service calls, tampered requests, each grant
boundary, self-review exclusions, category-level screen visibility, stale forms,
atomic publication and PostgreSQL revocation/use contention. Run dependency,
Django, migration-drift, OpenAPI, full-suite and clean-installation checks, plus
the four-job SQLite/PostgreSQL Python 3.11/3.12 CI matrix for the exact commit.
The previous [completion-boundary verification](COMPLETION_BOUNDARIES_AND_WORKFORCE.md)
is a baseline and does not by itself validate this later extension.

Other restricted operations, including incident/checklist review delegation,
remain outside these four capabilities. The implementation tracker retains
broader fine-grained permissions, audit review and facility acceptance work.
