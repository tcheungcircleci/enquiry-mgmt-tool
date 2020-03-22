import json
import logging
import os
import requests

from datetime import datetime, date
from django.conf import settings
from django.core.cache import cache
from mohawk import Sender
from requests.exceptions import RequestException
from rest_framework import status

import app.enquiries.ref_data as ref_data


DATA_HUB_METADATA_ENDPOINTS = (
    "country",
    "fdi-type",
    "investment-investor-type",
    "investment-involvement",
    "investment-project-stage",
    "investment-specific-programme",
    "investment-type",
    "referral-source-activity",
    "referral-source-website",
    "sector",
)

def dh_request(method, url, payload, request_headers=None, timeout=15):
    """
    Helper function to perform Data Hub request

    All requests have same headers, instead of repeating in each function
    they are added in the function. If there are any custom headers they
    can be provided using the request_headers argument.

    Each request has a timeout (default=15sec) failing which throws an
    exception which will be captured in Sentry
    """

    if request_headers:
        headers = request_headers
    else:
        # TODO: We don't need to send the access token in the headers
        # once SSO is integrated as it comes from SSO directly
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.DATA_HUB_ACCESS_TOKEN}",
        }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        elif method == "POST":
            response = requests.post(
                url, headers=headers, json=payload, timeout=timeout
            )
    except RequestException as e:
        logging.error(
            f"Error {e} while requesting {url}, request timeout set to {timeout} secs"
        )
        raise e

    return response


def _dh_fetch_metadata():
    """
    Fetches metadata from Data Hub as we need that to call Data Hub APIs
    """
    logging.info(f"Fetching metadata at {datetime.now()}")
    credentials = {
        "id": settings.DATA_HUB_HAWK_ID,
        "key": settings.DATA_HUB_HAWK_KEY,
        "algorithm": "sha256",
    }

    metadata = {"failed": []}
    for endpoint in DATA_HUB_METADATA_ENDPOINTS:
        meta_url = os.path.join(settings.DATA_HUB_METADATA_URL, endpoint)

        logging.info(f"Fetching {meta_url} ...")

        sender = Sender(
            credentials,
            meta_url,
            "GET",
            content=None,
            content_type=None,
            always_hash_content=False,
        )
        response = requests.get(
            meta_url, headers={"Authorization": sender.request_header}, timeout=10
        )
        if response.ok:
            metadata[endpoint] = response.json()
        else:
            metadata["failed"].append(endpoint)

    if metadata["failed"]:
        logging.error(
            f"Error fetching Data Hub metadata for endpoints: {metadata['failed']}"
        )

    return metadata


def dh_fetch_metadata(cache_key="metadata", expiry_secs=60 * 60):
    """
    Fetches and caches the metadata with an expiry time

    It check if the data is valid in cache, if it has expired then fetches again
    """

    try:
        cached_metadata = cache.get(cache_key)
        if not cached_metadata:
            logging.info("Metadata expired in cache, fetching again ...")
            cached_metadata = _dh_fetch_metadata()
            cache.set(cache_key, cached_metadata, timeout=expiry_secs)
            return cached_metadata

        logging.info(f"Metadata valid in cache (expiry_secs={expiry_secs})")
        return cached_metadata
    except Exception as e:
        logging.error(f"Error fetching metadata, {str(e)} ...")
        raise e


def map_to_datahub_id(refdata_value, dh_metadata, dh_category, target_key="name"):
    """
    Maps application reference data to Data Hub reference data and
    extracts the unique identifier

    Arguments
    ---------
    refdata_value: Human readable value of a choice field
    dh_metadata: Data Hub metadata dictionary
    dh_category: Data Hub metadata category
    target_key: key name with then metadata object

    Returns
    -------
    Data Hub uuid for the given refdata_value if available otherwise None

    """

    dh_data = list(
        filter(lambda d: d[target_key] == refdata_value, dh_metadata[dh_category])
    )

    return dh_data[0]["id"] if dh_data else None


def dh_company_search(company_name):
    """
    Peforms a Company name search using Data hub API.

    Returns list of subset of fields for each company found
    """
    companies = []
    url = settings.DATA_HUB_COMPANY_SEARCH_URL
    payload = {"name": company_name}

    response = dh_request("POST", url, payload)

    # It is not an error for us if the request fails, this can happen if the
    # Access token is invalid, consider that there are no matches however
    # user is notified of the error to take appropriate action
    # TODO: revisit once SSO integration is completed
    if not response.ok:
        return companies, response.json()

    for company in response.json()["results"]:
        address = company["address"]
        companies.append(
            {
                "datahub_id": company["id"],
                "name": company["name"],
                "address": {
                    "line_1": address["line_1"],
                    "line_2": address["line_2"],
                    "town": address["town"],
                    "county": address["county"],
                    "postcode": address["postcode"],
                    "country": address["country"]["name"],
                },
            }
        )

    return companies, None


def dh_contact_search(contact_name, company_id):
    """
    Peforms a Contact name search using Data hub API.

    Returns list of subset of fields for each contact found
    """
    contacts = []
    url = settings.DATA_HUB_CONTACT_SEARCH_URL
    payload = {"name": contact_name, "company": [company_id]}

    response = dh_request("POST", url, payload)

    if not response.ok:
        return contacts, response.json()

    for contact in response.json()["results"]:
        contacts.append(
            {
                "datahub_id": contact["id"],
                "first_name": contact["first_name"],
                "last_name": contact["last_name"],
                "job_title": contact["job_title"],
                "email": contact["email"],
                "phone": contact["telephone_number"],
            }
        )

    return contacts, None


def dh_contact_create(enquirer, company_id, primary=False):
    """
    Create a contact and associate with the given Company Id.

    Returns created contact and error if any
    """
    url = settings.DATA_HUB_CONTACT_CREATE_URL
    enquirer = enquirer.enquirer
    payload = {
        "first_name": enquirer.first_name,
        "last_name": enquirer.last_name,
        "job_title": enquirer.job_title,
        "company": company_id,
        "primary": primary,
        "telephone_countrycode": "NOT SET",
        "telephone_number": enquirer.phone,
        "email": enquirer.email,
        "address_same_as_company": True,
    }

    response = dh_request("POST", url, payload)
    if not response.ok:
        return None, response.json()

    return response.json(), None


def dh_adviser_search(adviser_name):
    """
    Peforms an Adviser search using Data hub API.

    Returns list of subset of fields for each Adviser found
    """
    advisers = []
    url = f"{settings.DATA_HUB_ADVISER_SEARCH_URL}/?autocomplete={adviser_name}"

    response = dh_request("GET", url, {})

    if response.status_code != status.HTTP_200_OK:
        return advisers, response.json()

    for adviser in response.json()["results"]:
        advisers.append(
            {
                "datahub_id": adviser["id"],
                "name": adviser["first_name"],
                "is_active": adviser["is_active"],
            }
        )

    return advisers, None


def get_dh_id(metadata_items, name):
    item = list(filter(lambda x: x["name"] == name, metadata_items))
    assert len(item) == 1
    return item[0]["id"]


def dh_investment_create(enquiry, metadata=None):
    """
    Creates an Investment in Data Hub using the data from the given Enquiry obj.

    Investment is only created if the Company corresponding to the Enquiry exists
    in DH otherwise error is returned.
    Enquirer details are added to the list of contacts for this company if not
    exists already. If this is the only contact then it will be made primary.
    """

    response = {
        "errors": []
    }

    # Allow creating of investments only if Company exists on DH
    if not enquiry.dh_company_id:
        response["errors"].append({"company": f"{enquiry.company_name} doesn't exist in Data Hub"})
        return response

    # Same enquiry cannot be submitted if it is already done once
    if (
        enquiry.date_added_to_datahub
        or enquiry.datahub_project_status != ref_data.DatahubProjectStatus.DEFAULT
    ):
        prev_submission_date = enquiry.date_added_to_datahub.strftime("%d %B %Y")
        stage = enquiry.get_datahub_project_status_display()
        response["errors"].append(
            {
                "enquiry": f"Enquiry can only be submitted once,"
                f" previously submitted on {prev_submission_date}, stage {stage}"
            }
        )
        return response

    if metadata is None:
        try:
            dh_metadata = dh_fetch_metadata()
        except Exception as e:
            response["errors"].append({"metadata": "Error fetching metadata"})
            return response
        dh_metadata = json.loads(dh_metadata)
    else:
        dh_metadata = metadata

    payload = {}

    company_id = enquiry.dh_company_id

    full_name = f"{enquiry.enquirer.first_name} {enquiry.enquirer.last_name}"
    contacts, error = dh_contact_search(full_name, company_id)
    if error:
        response["errors"].append({"contact_search": error})
        return response

    primary = not contacts
    # contact_response = dh_contact_create(enquiry, company_id, primary=primary)

    payload["name"] = enquiry.company_name
    payload["investor_company"] = company_id
    payload["description"] = enquiry.project_description
    payload["anonymous_description"] = enquiry.anonymised_project_description
    payload["estimated_land_date"] = enquiry.estimated_land_date.isoformat()

    payload["investment_type"] = get_dh_id(dh_metadata["investment-type"], "FDI")
    payload["fdi_type"] = map_to_datahub_id(
        enquiry.get_investment_type_display(), dh_metadata, "fdi-type"
    )
    payload["stage"] = get_dh_id(dh_metadata["investment-project-stage"], "Prospect")
    payload["investor_type"] = map_to_datahub_id(
        enquiry.get_new_existing_investor_display(),
        dh_metadata,
        "investment-investor-type",
    )
    payload["level_of_involvement"] = map_to_datahub_id(
        enquiry.get_investor_involvement_level_display(),
        dh_metadata,
        "investment-involvement",
    )
    payload["specific_programme"] = map_to_datahub_id(
        enquiry.get_specific_investment_programme_display(),
        dh_metadata,
        "investment-specific-programme",
    )
    # payload["client_contacts"] = [contact_id]
    payload["client_contacts"] = ["4ce2b0dd-a364-4e1e-9937-971f9001db0b"]

    if not enquiry.crm:
        response["errors"].append({"adviser": "Adviser name required, should not be empty"})
        return response

    advisers, error = dh_adviser_search(enquiry.crm)
    if error:
        response["errors"].append({"adviser_search": error})
        return response

    if not advisers:
        response["errors"].append({"adviser": f"Adviser {enquiry.crm} not found"})
        return response

    payload["client_relationship_manager"] = advisers[0]["datahub_id"]

    payload["sector"] = map_to_datahub_id(
        enquiry.get_primary_sector_display(), dh_metadata, "sector"
    )
    payload["business_activities"] = ["a2dbd807-ae52-421c-8d1d-88adfc7a506b"]

    # TODO: This will be the user who is submitting the data
    # Since the SSO integration hasn't happened yet, use Adviser id here
    payload["referral_source_adviser"] = advisers[0]["datahub_id"]
    payload["referral_source_activity"] = get_dh_id(
        dh_metadata["referral-source-activity"], "Website"
    )
    payload["referral_source_activity_website"] = get_dh_id(
        dh_metadata["referral-source-website"], "Invest in GREAT Britain"
    )

    url = settings.DATA_HUB_INVESTMENT_CREATE_URL

    try:
        result = dh_request("POST", url, payload)
        response["result"] = result
    except Exception as e:
        response["errors"].append({"investment_create": f"Error creating investment, {str(e)}"})
        return response

    if result.ok:
        enquiry.datahub_project_status = ref_data.DatahubProjectStatus.PROSPECT
        enquiry.date_added_to_datahub = date.today()
        enquiry.save()

    return response
