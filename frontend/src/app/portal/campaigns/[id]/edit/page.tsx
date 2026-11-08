'use client'

import { useParams } from 'next/navigation'
import CampaignSelfService from '../../CampaignSelfService'

export default function EditPortalCampaignPage() {
  const params = useParams<{ id: string }>()
  return <CampaignSelfService id={Number(params.id)} />
}
