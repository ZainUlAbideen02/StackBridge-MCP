"use client";

import React, { useEffect, useState } from "react";

interface Team {
  id: string;
  name: string;
}

interface BillingAccount {
  id: string;
  userId: string;
  plan: string;
  balance: number;
}

export default function UserProfile({ userId }: { userId: string }) {
  const [teams, setTeams] = useState<Team[]>([]);
  const [billing, setBilling] = useState<BillingAccount | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    async function loadData() {
      try {
        // Static fetch call
        const teamsRes = await fetch("/api/v1/teams");
        if (teamsRes.ok) {
          const teamsData = await teamsRes.json();
          setTeams(teamsData);
        }

        // Dynamic template string fetch call
        const billingRes = await fetch(`/api/v1/users/${userId}/billing`);
        if (billingRes.ok) {
          const billingData = await billingRes.json();
          setBilling(billingData);
        }
      } catch (err) {
        console.error("Failed to load user profile data", err);
      } finally {
        setLoading(false);
      }
    }

    if (userId) {
      loadData();
    }
  }, [userId]);

  if (loading) {
    return <div>Loading profile...</div>;
  }

  return (
    <div className="p-4 space-y-4">
      <h1 className="text-xl font-bold">User Profile</h1>
      <section>
        <h2 className="text-lg font-semibold">Teams</h2>
        <ul>
          {teams.map((team) => (
            <li key={team.id}>{team.name}</li>
          ))}
        </ul>
      </section>
      {billing && (
        <section>
          <h2 className="text-lg font-semibold">Billing Details</h2>
          <p>Plan: {billing.plan}</p>
          <p>Balance: ${billing.balance}</p>
        </section>
      )}
    </div>
  );
}
