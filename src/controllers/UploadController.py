import shutil
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from helpers import FileTooLargeError, buffer_and_hash, sanitize_filename, unique_storage_name
from helpers.visibility import can_see, is_pre_sign_in
from models.db_schema import Document, DocumentPage, Offer, PipelineJob, User
from models.enums import JobStatus, ResponseSignal

from .BaseController import BaseController
from .PersistController import OfferNotFoundError


class DocumentValidationError(Exception):
    def __init__(self, signal: ResponseSignal, message: str):
        self.signal = signal
        self.message = message
        super().__init__(message)


class OfferAlreadyProcessedError(Exception):
    """Raised when trying to abandon an offer that has already been through
    persist - abandoning it would destroy real data, not clean up a partial
    run, so this refuses outright rather than silently no-op-ing."""

    def __init__(self, offer_id: int):
        self.offer_id = offer_id
        super().__init__(f"Offer {offer_id} has already been persisted and cannot be abandoned")


class OfferNotLatestVersionError(Exception):
    """Raised when trying to version an offer that isn't the current tip of
    its chain - either because it's genuinely an older version, or because a
    concurrent request already versioned it first."""

    def __init__(self, offer_id: int):
        self.offer_id = offer_id
        super().__init__(f"Offer {offer_id} is not the latest version of its chain")


def _blank_to_none(value: str | None) -> str | None:
    """An untouched form field and a field the user cleared should read the
    same way - both mean "nothing was typed", not the literal empty string."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


class UploadController(BaseController):
    def __init__(self, db: AsyncSession):
        super().__init__()
        self.db = db

    async def create_offer(
        self,
        commit: bool = True,
        owner=None,
        project_name_entered: str | None = None,
        rfq_number: str | None = None,
    ) -> int:
        """Creates the empty offer row an upload attaches its files to.

        `owner` is the signed-in user. Their department is COPIED onto the row
        rather than read through the user later, so somebody transferring
        between departments does not drag their old offers with them - see
        helpers/visibility.py.

        `project_name_entered` and `rfq_number` are what the person filing the
        offer typed, if anything - both optional, both blank-to-null so an
        empty form field reads the same as one never sent. They are stored
        as-is: `project_name_entered` never overwrites `project_name_original`
        (see `Offer.project_name_entered`'s own comment - that is what
        `offer_versioning.check_same_offer_identity` compares, and disarming it
        silently would be worse than leaving both fields blank).
        """
        offer = Offer(
            project_name_entered=_blank_to_none(project_name_entered),
            rfq_number=_blank_to_none(rfq_number),
        )
        if owner is not None:
            offer.created_by_user_id = owner.id
            offer.created_by_department = owner.department or ""
        self.db.add(offer)
        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(offer)
        return offer.id

    async def create_offer_version(self, target_offer_id: int, commit: bool = True, owner=None) -> int:
        """Creates a new `Offer` row as the next version of `target_offer_id`'s
        chain, and flips the target's `is_active_latest` off - this is
        speculative (like `create_offer`, not yet committed unless
        `commit=True`), so a later pipeline failure can undo it with a plain
        session rollback rather than needing to manually unwind the link.

        `SELECT ... FOR UPDATE` locks the target row for the rest of this
        transaction, so the `is_active_latest` check right after it is the
        single authoritative check (the route no longer needs, and must not
        do, a separate unlocked check before calling this) - two concurrent
        requests versioning the same offer would otherwise both see it as
        still active and both succeed, leaving two active branches."""
        result = await self.db.execute(select(Offer).where(Offer.id == target_offer_id).with_for_update())
        target = result.scalar_one_or_none()
        if target is None:
            raise OfferNotFoundError(target_offer_id)
        if not target.is_active_latest:
            raise OfferNotLatestVersionError(target_offer_id)

        new_offer = Offer(
            root_offer_id=target.root_offer_id or target.id,
            parent_offer_id=target.id,
            is_active_latest=True,
            # A version answers the same RFQ under the same typed name as the
            # rest of its chain - there is nothing new to ask the uploader, and
            # leaving these blank would drop a v1's RFQ the moment v2 arrived,
            # breaking the compare screen's grouping and the offers filter for
            # a chain that has not actually changed identity.
            rfq_number=target.rfq_number,
            project_name_entered=target.project_name_entered,
        )
        # A version stays in its chain's department whoever uploads it. Given
        # the uploader's instead, a version an admin uploaded onto another
        # department's offer would belong to the admin's department - and
        # through it, persist's identity check would name the parent's supplier
        # and project to that department, and abandoning it would restore the
        # parent's is_active_latest. Only a pre-sign-in chain, which belongs to
        # nobody, is claimed by whoever versions it.
        if owner is not None and is_pre_sign_in(target.created_by_user_id, target.created_by_department):
            new_offer.created_by_user_id = owner.id
            new_offer.created_by_department = owner.department or ""
        else:
            new_offer.created_by_user_id = owner.id if owner is not None else target.created_by_user_id
            new_offer.created_by_department = target.created_by_department
        self.db.add(new_offer)
        target.is_active_latest = False

        if commit:
            await self.db.commit()
        else:
            await self.db.flush()
        await self.db.refresh(new_offer)
        return new_offer.id

    async def validate_and_buffer(
        self, file: UploadFile, allowed_types: list[str] | None = None
    ) -> tuple[bytes, str, int]:
        """Buffers a file, checking its type and size.

        `allowed_types` overrides the offer-document allowlist. Override
        evidence needs a different one - an .eml or .msg is the client's
        primary evidence type and must never be accepted as an offer document,
        because nothing downstream can parse one.
        """
        permitted = allowed_types if allowed_types is not None else self.app_settings.FILE_ALLOWED_TYPES
        if file.content_type not in permitted:
            raise DocumentValidationError(
                ResponseSignal.FILE_TYPE_NOT_SUPPORTED,
                f"Unsupported file type: {file.content_type}",
            )

        max_size_bytes = self.app_settings.FILE_MAX_SIZE * 1024 * 1024
        try:
            content, checksum, size = await buffer_and_hash(
                file, self.app_settings.FILE_DEFAULT_CHUNK_SIZE, max_size_bytes
            )
        except FileTooLargeError:
            raise DocumentValidationError(
                ResponseSignal.FILE_SIZE_EXCEEDED,
                f"File exceeds maximum size of {self.app_settings.FILE_MAX_SIZE}MB",
            ) from None

        if not content:
            raise DocumentValidationError(ResponseSignal.FILE_EMPTY, "File is empty")

        return content, checksum, size

    async def find_duplicate(
        self, checksum: str, user: User, *, current_offer_id: int | None = None
    ) -> tuple[Document, bool] | None:
        """The document already stored with this content, and whether `user`
        may see the offer it sits under.

        Checksums are unique across every department, so a duplicate has to be
        reported either way - but which offer and document hold it is only for
        someone who could open them. Reads the offer's ownership columns, not
        the offer, for the reason given in `ensure_offer_visible`.

        A cancelled or failed run deliberately keeps its offer and documents
        (see `abandon_offer`) so a rerun costs a re-read, not a re-upload - but
        that only helps someone who knows to use Rerun. Someone who simply
        tries the same file again would otherwise be told it is a duplicate of
        their own dead draft forever, with no way out short of finding it in
        the jobs list. So: if this checksum's only match is the *uploader's
        own* offer, that offer never reached persist, and nothing is currently
        queued or running for it, reclaim it here and report no duplicate -
        the new upload proceeds as if the dead draft never existed.
        `current_offer_id` excludes the offer this very request is writing
        to, so two identical files in one batch still report as a duplicate
        of each other rather than the first one being deleted out from under
        the second.
        """
        row = (
            await self.db.execute(
                select(Document, Offer.created_by_user_id, Offer.created_by_department)
                .outerjoin(Offer, Offer.id == Document.offer_id)
                .where(Document.file_checksum == checksum)
            )
        ).one_or_none()
        if row is None:
            return None
        document, owner_id, department = row

        if (
            owner_id == user.id
            and document.offer_id is not None
            and document.offer_id != current_offer_id
        ):
            # Locked, not `db.get` - an offer id crossing the FK from a
            # brand-new PipelineJob (e.g. someone hitting Rerun on this same
            # dead draft in another tab right now) has to wait for this
            # transaction to finish, or the active-job check below could pass
            # a heartbeat before that insert lands and then delete the offer
            # out from under the job it just gained.
            offer = (
                await self.db.execute(
                    select(Offer).where(Offer.id == document.offer_id).with_for_update()
                )
            ).scalar_one_or_none()
            if offer is not None and offer.persisted_at is None:
                active_job = (
                    await self.db.execute(
                        select(PipelineJob.job_id)
                        .where(
                            PipelineJob.offer_id == offer.id,
                            PipelineJob.status.in_(
                                [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
                            ),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if active_job is None:
                    try:
                        await self.abandon_offer(offer.id)
                    except OfferAlreadyProcessedError:
                        # Persisted (or reached persist) between the check
                        # above and here - a real offer, not a dead draft.
                        # Fall through and report it as the duplicate it is.
                        pass
                    else:
                        return None

        return document, can_see(user, owner_id, department)

    async def save_document(
        self,
        offer_id: int,
        original_filename: str,
        file_type: str,
        checksum: str,
        content: bytes,
        commit: bool = True,
    ) -> Document:
        offer_dir = Path(self.files_dir) / str(offer_id)
        offer_dir.mkdir(parents=True, exist_ok=True)

        safe_filename = sanitize_filename(original_filename)
        storage_filename = unique_storage_name(offer_dir, safe_filename)
        destination = offer_dir / storage_filename
        relative_path = f"assets/offers/{offer_id}/{storage_filename}"

        destination.write_bytes(content)

        document = Document(
            original_filename=original_filename,
            storage_path=relative_path,
            file_type=file_type,
            file_checksum=checksum,
            offer_id=offer_id,
        )
        self.db.add(document)
        try:
            if commit:
                await self.db.commit()
            else:
                await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            destination.unlink(missing_ok=True)
            raise DocumentValidationError(
                ResponseSignal.FILE_ALREADY_EXISTS,
                "This file was already uploaded by a concurrent request.",
            ) from None
        except Exception:
            await self.db.rollback()
            destination.unlink(missing_ok=True)
            raise

        await self.db.refresh(document)
        return document

    async def abandon_offer(self, offer_id: int) -> None:
        """Deletes an offer that never made it through persist - called when
        a pipeline run is abandoned partway (a step failed, the user
        navigated away, or the tab was closed while a stage was still
        running) so nothing partial is left in the database or on disk.
        Idempotent (a no-op if the offer is already gone, e.g. the upload
        step's own all-files-failed cleanup already removed it). Guarded by
        `sanity_check_status`/`verification_status` both still being null -
        the same signal `PersistController.persist_offer` itself sets on
        completion - so this can never be pointed at a real, already-
        persisted offer by mistake."""
        offer = await self.db.get(Offer, offer_id)
        if offer is None:
            return
        # `persisted_at` is the precise marker that this offer completed the
        # persist stage; the status columns are kept in the check as well so
        # rows written before that column existed are still protected.
        if (
            offer.persisted_at is not None
            or offer.sanity_check_status is not None
            or offer.verification_status is not None
        ):
            raise OfferAlreadyProcessedError(offer_id)

        if offer.parent_offer_id is not None:
            parent = await self.db.get(Offer, offer.parent_offer_id)
            if parent is not None:
                # Only if nothing has already superseded this one. Abandoning
                # a dead version attempt must not resurrect a parent that a
                # NEWER version already replaced - re-uploading the same file
                # after a cancel creates the new version (flipping the
                # parent inactive) before this abandon ever runs, so a
                # sibling that is already `is_active_latest` means the chain
                # has moved on and the parent must be left alone. Excludes
                # `offer` itself: a version row is created `is_active_latest
                # = True` (`create_offer_version`) and nothing flips that off
                # before it gets here to be deleted, so without this
                # exclusion the offer would always match its own query and
                # the parent would never be restored, even legitimately.
                sibling_active = (
                    await self.db.execute(
                        select(Offer.id)
                        .where(
                            Offer.parent_offer_id == parent.id,
                            Offer.is_active_latest.is_(True),
                            Offer.id != offer.id,
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if sibling_active is None:
                    parent.is_active_latest = True

        document_ids = (
            (await self.db.execute(select(Document.document_id).where(Document.offer_id == offer_id)))
            .scalars()
            .all()
        )
        if document_ids:
            await self.db.execute(delete(DocumentPage).where(DocumentPage.file_id.in_(document_ids)))
            await self.db.execute(delete(Document).where(Document.offer_id == offer_id))
        await self.db.delete(offer)
        await self.db.commit()

        shutil.rmtree(Path(self.files_dir) / str(offer_id), ignore_errors=True)
